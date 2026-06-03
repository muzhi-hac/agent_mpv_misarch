#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


DEFAULT_GRAPHQL_URL = "http://34.40.117.201:8080/graphql"
DEFAULT_MCP_URL = "http://34.40.117.201:8001/mcp"
DEFAULT_MODEL_BASE_URL = "https://yybb.codes"
DEFAULT_MODEL = "gpt-5.4"
DEFAULT_RESULTS_DIR = "eval"
DEFAULT_KEYCLOAK_CLIENT_ID = "frontend"
DEFAULT_KEYCLOAK_USERNAME = "gatling"
DEFAULT_KEYCLOAK_PASSWORD = "123"

LIST_PRODUCTS_QUERY = """
query ListProducts($first: Int!) {
  products(first: $first) {
    nodes {
      id
      defaultVariant {
        id
        currentVersion {
          name
          description
          retailPrice
        }
      }
      categories(first: 10) {
        nodes {
          name
        }
      }
    }
  }
}
"""

GET_PRODUCT_QUERY = """
query GetProduct($id: UUID!) {
  product(id: $id) {
    id
    defaultVariant {
      id
      currentVersion {
        name
        description
        retailPrice
      }
    }
    categories(first: 10) {
      nodes {
        name
      }
    }
  }
}
"""

GET_CURRENT_USER_QUERY = """
query GetCurrentUserForPendingOrder {
  currentUser {
    id
  }
}
"""

GET_ACTIVE_ADDRESSES_QUERY = """
query GetActiveAddressesForPendingOrder {
  currentUser {
    addresses(first: 5, filter: {isArchived: false}) {
      totalCount
      nodes {
        id
      }
    }
  }
}
"""

GET_PAYMENT_INFORMATIONS_QUERY = """
query GetPaymentInformationsForPendingOrder {
  currentUser {
    paymentInformations(first: 5) {
      totalCount
      nodes {
        id
        paymentMethod
      }
    }
  }
}
"""

GET_SHIPMENT_METHODS_QUERY = """
query GetShipmentMethodsForPendingOrder {
  shipmentMethods(first: 5, filter: {isArchived: false}) {
    totalCount
    nodes {
      id
      name
    }
  }
}
"""

CREATE_SHOPPING_CART_ITEM_MUTATION = """
mutation CreateShoppingcartItem($input: CreateShoppingCartItemInput!) {
  createShoppingcartItem(input: $input) {
    id
    count
    productVariant {
      id
    }
  }
}
"""

CREATE_ORDER_MUTATION = """
mutation CreateOrder($input: CreateOrderInput!) {
  createOrder(input: $input) {
    id
    orderStatus
  }
}
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def default_keycloak_token_url() -> str:
    token_url = os.environ.get("MISARCH_KEYCLOAK_TOKEN_URL", "").strip()
    if token_url:
        return token_url

    keycloak_url = os.environ.get("KEYCLOAK_URL", "").strip()
    if not keycloak_url:
        return ""

    realm = os.environ.get("REALM", "Misarch").strip() or "Misarch"
    return (
        keycloak_url.rstrip("/")
        + f"/realms/{realm}/protocol/openid-connect/token"
    )


def load_api_key() -> str:
    env_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if env_key:
        return env_key

    auth_path = pathlib.Path.home() / ".codex" / "auth.json"
    try:
        payload = json.loads(auth_path.read_text())
    except FileNotFoundError as exc:
        raise RuntimeError(f"missing auth file: {auth_path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid auth JSON: {auth_path}") from exc

    api_key = payload.get("OPENAI_API_KEY")
    if not isinstance(api_key, str) or not api_key.strip():
        raise RuntimeError("OPENAI_API_KEY is missing or empty")
    return api_key.strip()


def parse_sse_json(body: str) -> dict[str, Any]:
    data_lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())

    raw = "\n".join(data_lines).strip() if data_lines else body.strip()
    if not raw:
        return {}
    return json.loads(raw)


def post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float = 30,
) -> tuple[dict[str, Any], Any]:
    request_headers = {
        "Content-Type": "application/json",
        **(headers or {}),
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )

    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"POST {url} failed with HTTP {exc.code}: {body[:800]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"POST {url} failed: {exc.reason}") from exc

    body = response.read().decode("utf-8", errors="replace")
    if not body.strip():
        return {}, response

    content_type = response.headers.get("Content-Type", "")
    if "text/event-stream" in content_type:
        return parse_sse_json(body), response
    return json.loads(body), response


def responses_api_call(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "input": prompt,
        "max_output_tokens": 700,
    }

    errors: list[str] = []
    for path in ("/v1/responses", "/responses"):
        try:
            response, _ = post_json(
                base_url.rstrip("/") + path,
                payload,
                headers=headers,
                timeout=60,
            )
            return extract_response_text(response)
        except RuntimeError as exc:
            message = str(exc)
            errors.append(message)
            if "HTTP 404" not in message:
                break

    raise RuntimeError("\n".join(errors))


def keycloak_token(args: argparse.Namespace) -> str:
    if not args.keycloak_token_url:
        raise RuntimeError(
            "--keycloak-token-url or MISARCH_KEYCLOAK_TOKEN_URL is required "
            "when --include-order-test is enabled and no bearer token is provided"
        )

    form = urllib.parse.urlencode(
        {
            "grant_type": args.keycloak_grant_type,
            "client_id": args.keycloak_client_id,
            "username": args.keycloak_username,
            "password": args.keycloak_password,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        args.keycloak_token_url,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        response = urllib.request.urlopen(request, timeout=30)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Keycloak token request failed with HTTP {exc.code}: {body[:800]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Keycloak token request failed: {exc.reason}") from exc

    with response:
        payload = json.loads(response.read().decode("utf-8"))
    token = payload.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError(f"Keycloak token response has no access_token: {payload}")
    return token.strip()


def load_graphql_bearer_token(args: argparse.Namespace) -> str:
    token = args.graphql_bearer_token.strip()
    if token:
        return token
    return keycloak_token(args)


def bearer_headers(token: str | None) -> dict[str, str]:
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def extract_response_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    chunks: list[str] = []
    output = response.get("output", [])
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content", [])
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)

    if chunks:
        return "\n".join(chunks).strip()

    return json.dumps(response, ensure_ascii=False, indent=2)


def graphql_request(
    graphql_url: str,
    query: str,
    variables: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)

    response, _ = post_json(
        graphql_url,
        {
            "query": query,
            "variables": variables,
        },
        headers=request_headers,
        timeout=20,
    )
    if response.get("errors"):
        raise RuntimeError(json.dumps(response["errors"], ensure_ascii=False))
    data = response.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"GraphQL response has no data object: {response}")
    return response


def normalize_graphql_product(node: dict[str, Any] | None) -> dict[str, Any] | None:
    if not node:
        return None

    variant = node.get("defaultVariant") or {}
    version = variant.get("currentVersion") or {}
    categories_page = node.get("categories") or {}
    category_nodes = categories_page.get("nodes") or []

    return {
        "product_id": node.get("id"),
        "variant_id": variant.get("id"),
        "name": version.get("name"),
        "description": version.get("description"),
        "retail_price_cents": version.get("retailPrice"),
        "currency": "EUR",
        "categories": [
            category.get("name")
            for category in category_nodes
            if isinstance(category, dict) and category.get("name")
        ],
    }


def mcp_post(
    mcp_url: str,
    payload: dict[str, Any],
    session_id: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    headers = {
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    response_payload, response = post_json(
        mcp_url,
        payload,
        headers=headers,
        timeout=15,
    )
    return response_payload, response.headers.get("Mcp-Session-Id")


def require_result(response: dict[str, Any]) -> dict[str, Any]:
    if "error" in response:
        raise RuntimeError(json.dumps(response["error"], ensure_ascii=False))
    result = response.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"JSON-RPC response has no object result: {response}")
    return result


def call_mcp_tool(
    mcp_url: str,
    session_id: str,
    name: str,
    arguments: dict[str, Any],
    request_id: int,
) -> dict[str, Any]:
    response, _ = mcp_post(
        mcp_url,
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments,
            },
        },
        session_id=session_id,
    )
    result = require_result(response)
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        raise RuntimeError(f"tool {name} returned no structuredContent: {result}")
    return structured


def build_native_graphql_prompt(result: dict[str, Any]) -> str:
    evidence = {
        "path": "native_graphql",
        "raw_list_response": result["raw_list_response"],
        "raw_detail_response": result["raw_detail_response"],
        "normalized_detail_for_comparison": result["normalized_detail"],
        "observations": {
            "tool_discovery": "not provided by raw GraphQL",
            "explicit_side_effects": "not provided by raw GraphQL response",
            "explicit_runtime_source": "not provided by raw GraphQL response",
        },
    }
    return (
        "你是一个外部 agent 测试员。你这次直接访问 MiSArch 原生 GraphQL API。\n"
        "只基于下面 JSON 证据回答，不要编造。请用中文简短说明：\n"
        "1. 是否成功读取真实商品；\n"
        "2. 原生 GraphQL 返回的数据结构特点；\n"
        "3. 它是否提供 tool discovery、side effects、runtime/source_service；\n"
        "4. 作为 agent baseline 的优缺点。\n\n"
        f"JSON evidence:\n{json.dumps(evidence, ensure_ascii=False, indent=2)}"
    )


def build_mcp_prompt(result: dict[str, Any]) -> str:
    evidence = {
        "path": "mcp_gateway",
        "mcp_tools": result["tool_names"],
        "list_products_result": result["product_list"],
        "get_product_result": result["product_detail"],
        "observations": {
            "tool_discovery": "provided by tools/list",
            "explicit_side_effects": result["has_explicit_side_effects"],
            "explicit_runtime_source": result["has_explicit_runtime_source"],
        },
    }
    return (
        "你是一个外部 agent 测试员。你这次通过 MCP gateway 访问 MiSArch。\n"
        "只基于下面 JSON 证据回答，不要编造。请用中文简短说明：\n"
        "1. agent 发现了哪些 MCP 工具；\n"
        "2. 是否成功读取真实商品；\n"
        "3. runtime/source_service 和 side effects 是否明确；\n"
        "4. 作为 agent-facing interface 的优缺点。\n\n"
        f"JSON evidence:\n{json.dumps(evidence, ensure_ascii=False, indent=2)}"
    )


def maybe_agent_report(
    args: argparse.Namespace,
    api_key: str | None,
    prompt: str,
) -> dict[str, Any]:
    if args.skip_llm:
        return {
            "ok": True,
            "skipped": True,
            "duration_ms": 0.0,
            "text": "LLM report skipped by --skip-llm.",
        }

    if not api_key:
        raise RuntimeError("api_key is required unless --skip-llm is used")

    start = time.perf_counter()
    try:
        text = responses_api_call(args.model_base_url, api_key, args.model, prompt)
        return {
            "ok": True,
            "skipped": False,
            "duration_ms": elapsed_ms(start),
            "text": text,
        }
    except Exception as exc:
        return {
            "ok": False,
            "skipped": False,
            "duration_ms": elapsed_ms(start),
            "error": str(exc),
        }


def parse_id_list(raw: str) -> list[str]:
    return [value.strip() for value in raw.split(",") if value.strip()]


def first_connection_node(
    response: dict[str, Any],
    path: list[str],
    label: str,
) -> dict[str, Any]:
    current: Any = response.get("data", {})
    for key in path:
        if not isinstance(current, dict):
            raise RuntimeError(f"{label} path {'.'.join(path)} is not an object")
        current = current.get(key)

    if not isinstance(current, dict):
        raise RuntimeError(f"{label} connection is missing")
    nodes = current.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise RuntimeError(f"no {label} available")
    node = nodes[0]
    if not isinstance(node, dict) or not node.get("id"):
        raise RuntimeError(f"first {label} node has no id: {node}")
    return node


def current_user_id(
    args: argparse.Namespace,
    token: str,
) -> tuple[str, dict[str, Any]]:
    response = graphql_request(
        args.graphql_url,
        GET_CURRENT_USER_QUERY,
        {},
        bearer_headers(token),
    )
    user = response.get("data", {}).get("currentUser")
    if not isinstance(user, dict) or not user.get("id"):
        raise RuntimeError(f"currentUser query returned no id: {response}")
    return str(user["id"]), response


def resolve_pending_order_input(
    args: argparse.Namespace,
    native: dict[str, Any],
    mcp: dict[str, Any],
    token: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if args.order_quantity < 1 or args.order_quantity > 3:
        raise RuntimeError("--order-quantity must be between 1 and 3")

    native_product = product_from_native(native) or {}
    mcp_product = product_from_mcp(mcp) or {}
    product_variant_id = (
        args.order_product_variant_id
        or native_product.get("variant_id")
        or mcp_product.get("variant_id")
    )
    if not product_variant_id:
        raise RuntimeError(
            "pending order requires --order-product-variant-id or a successful "
            "product read path with variant_id"
        )

    resolution: dict[str, Any] = {
        "product_variant_source": (
            "cli"
            if args.order_product_variant_id
            else "native_graphql_or_mcp_read_result"
        )
    }

    user_response: dict[str, Any] | None = None
    user_id = args.order_user_id
    if user_id:
        resolution["user_source"] = "cli"
    else:
        user_id, user_response = current_user_id(args, token)
        resolution["user_source"] = "currentUser"

    shipment_method_id = args.order_shipment_method_id
    if shipment_method_id:
        resolution["shipment_method_source"] = "cli"
    else:
        shipment_response = graphql_request(
            args.graphql_url,
            GET_SHIPMENT_METHODS_QUERY,
            {},
            bearer_headers(token),
        )
        shipment_method = first_connection_node(
            shipment_response,
            ["shipmentMethods"],
            "shipment method",
        )
        shipment_method_id = str(shipment_method["id"])
        resolution["shipment_method_source"] = "shipmentMethods"
        resolution["shipment_method"] = shipment_method

    shipment_address_id = args.order_shipment_address_id
    invoice_address_id = args.order_invoice_address_id
    if shipment_address_id and invoice_address_id:
        resolution["address_source"] = "cli"
    else:
        addresses_response = graphql_request(
            args.graphql_url,
            GET_ACTIVE_ADDRESSES_QUERY,
            {},
            bearer_headers(token),
        )
        address = first_connection_node(
            addresses_response,
            ["currentUser", "addresses"],
            "active address",
        )
        shipment_address_id = shipment_address_id or str(address["id"])
        invoice_address_id = invoice_address_id or shipment_address_id
        resolution["address_source"] = "currentUser.addresses"
        resolution["address"] = address

    payment_information_id = args.order_payment_information_id
    if payment_information_id:
        resolution["payment_information_source"] = "cli"
    else:
        payment_response = graphql_request(
            args.graphql_url,
            GET_PAYMENT_INFORMATIONS_QUERY,
            {},
            bearer_headers(token),
        )
        payment_information = first_connection_node(
            payment_response,
            ["currentUser", "paymentInformations"],
            "payment information",
        )
        payment_information_id = str(payment_information["id"])
        resolution["payment_information_source"] = "currentUser.paymentInformations"
        resolution["payment_information"] = payment_information

    if user_response is not None:
        resolution["current_user_response"] = user_response

    order_input = {
        "user_id": str(user_id),
        "product_variant_id": str(product_variant_id),
        "quantity": args.order_quantity,
        "shipment_method_id": str(shipment_method_id),
        "shipment_address_id": str(shipment_address_id),
        "invoice_address_id": str(invoice_address_id),
        "payment_information_id": str(payment_information_id),
        "coupon_ids": parse_id_list(args.order_coupon_ids),
    }
    return order_input, resolution


def raw_graphql_cart_variables(
    order_input: dict[str, Any],
) -> dict[str, Any]:
    return {
        "input": {
            "id": order_input["user_id"],
            "shoppingCartItem": {
                "count": order_input["quantity"],
                "productVariantId": order_input["product_variant_id"],
            },
        },
    }


def normalize_native_pending_order(
    cart_response: dict[str, Any],
    order_response: dict[str, Any],
) -> dict[str, Any]:
    cart = (
        cart_response.get("data", {})
        .get("createShoppingcartItem", {})
    )
    order = order_response.get("data", {}).get("createOrder", {})
    return {
        "order_id": order.get("id"),
        "order_status": order.get("orderStatus"),
        "shopping_cart_item_id": cart.get("id"),
        "shopping_cart_item_count": cart.get("count"),
        "product_variant_id": (cart.get("productVariant") or {}).get("id"),
    }


def run_native_pending_order_baseline(
    args: argparse.Namespace,
    order_input: dict[str, Any],
    token: str,
) -> dict[str, Any]:
    start = time.perf_counter()
    headers = bearer_headers(token)

    cart_start = time.perf_counter()
    cart_variables = raw_graphql_cart_variables(order_input)
    cart_response = graphql_request(
        args.graphql_url,
        CREATE_SHOPPING_CART_ITEM_MUTATION,
        cart_variables,
        headers,
    )
    cart_duration_ms = elapsed_ms(cart_start)
    cart = cart_response.get("data", {}).get("createShoppingcartItem", {})
    shopping_cart_item_id = cart.get("id")
    if not shopping_cart_item_id:
        raise RuntimeError(
            f"raw GraphQL createShoppingcartItem returned no id: {cart_response}"
        )

    order_variables = {
        "input": {
            "userId": order_input["user_id"],
            "orderItemInputs": [
                {
                    "shoppingCartItemId": shopping_cart_item_id,
                    "shipmentMethodId": order_input["shipment_method_id"],
                    "couponIds": order_input["coupon_ids"],
                }
            ],
            "shipmentAddressId": order_input["shipment_address_id"],
            "invoiceAddressId": order_input["invoice_address_id"],
            "paymentInformationId": order_input["payment_information_id"],
        },
    }

    order_start = time.perf_counter()
    order_response = graphql_request(
        args.graphql_url,
        CREATE_ORDER_MUTATION,
        order_variables,
        headers,
    )
    order_duration_ms = elapsed_ms(order_start)
    normalized = normalize_native_pending_order(cart_response, order_response)

    return {
        "path": "native_graphql_pending_order_baseline",
        "success": True,
        "endpoint": args.graphql_url,
        "started_at": utc_now(),
        "duration_ms": elapsed_ms(start),
        "cart_duration_ms": cart_duration_ms,
        "order_duration_ms": order_duration_ms,
        "cart_mutation": CREATE_SHOPPING_CART_ITEM_MUTATION,
        "order_mutation": CREATE_ORDER_MUTATION,
        "cart_variables": cart_variables,
        "order_variables": order_variables,
        "raw_cart_response": cart_response,
        "raw_order_response": order_response,
        "normalized": normalized,
        "has_tool_discovery": False,
        "has_input_schema": False,
        "has_explicit_side_effects": False,
        "has_explicit_runtime_source": False,
        "known_side_effects": (
            "creates a shopping cart item and a pending order; does not place "
            "the order or trigger payment"
        ),
    }


def run_mcp_pending_order_agent(
    args: argparse.Namespace,
    order_input: dict[str, Any],
) -> dict[str, Any]:
    start = time.perf_counter()
    initialize, session_id = mcp_post(
        args.mcp_url,
        {
            "jsonrpc": "2.0",
            "id": 101,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {
                    "name": "misarch-pending-order-comparison-agent",
                    "version": "0.1",
                },
            },
        },
    )
    initialize_result = require_result(initialize)
    if not session_id:
        raise RuntimeError("MCP initialize did not return Mcp-Session-Id")

    mcp_post(
        args.mcp_url,
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
        session_id=session_id,
    )

    call_start = time.perf_counter()
    result = call_mcp_tool(
        args.mcp_url,
        session_id,
        "create_pending_order",
        order_input,
        102,
    )

    return {
        "path": "mcp_gateway_pending_order_tool",
        "success": True,
        "endpoint": args.mcp_url,
        "started_at": utc_now(),
        "duration_ms": elapsed_ms(start),
        "tool_call_duration_ms": elapsed_ms(call_start),
        "server_info": initialize_result.get("serverInfo"),
        "tool_name": "create_pending_order",
        "arguments": order_input,
        "result": result,
        "has_tool_discovery": True,
        "has_input_schema": True,
        "has_explicit_side_effects": bool(result.get("side_effects")),
        "has_explicit_runtime_source": bool(
            result.get("runtime") and result.get("source_service")
        ),
    }


def pending_status(result: dict[str, Any]) -> str | None:
    normalized = result.get("normalized")
    if isinstance(normalized, dict):
        value = normalized.get("order_status")
        return str(value) if value is not None else None
    tool_result = result.get("result")
    if isinstance(tool_result, dict):
        value = tool_result.get("order_status")
        return str(value) if value is not None else None
    return None


def pending_order_id(result: dict[str, Any]) -> str | None:
    normalized = result.get("normalized")
    if isinstance(normalized, dict):
        value = normalized.get("order_id")
        return str(value) if value is not None else None
    tool_result = result.get("result")
    if isinstance(tool_result, dict):
        value = tool_result.get("order_id")
        return str(value) if value is not None else None
    return None


def compare_pending_order_paths(
    native_order: dict[str, Any],
    mcp_order: dict[str, Any],
) -> dict[str, Any]:
    if not native_order.get("success") or not mcp_order.get("success"):
        return {
            "comparable": False,
            "reason": "one or both pending order paths failed",
        }

    native_status = pending_status(native_order)
    mcp_status = pending_status(mcp_order)
    same_status = native_status == mcp_status
    native_id = pending_order_id(native_order)
    mcp_id = pending_order_id(mcp_order)

    return {
        "comparable": True,
        "same_order_status": same_status,
        "both_pending": native_status == "PENDING" and mcp_status == "PENDING",
        "both_have_order_id": bool(native_id and mcp_id),
        "different_order_ids_expected": bool(native_id and mcp_id and native_id != mcp_id),
        "native_order_status": native_status,
        "mcp_order_status": mcp_status,
        "native_order_id": native_id,
        "mcp_order_id": mcp_id,
        "native_duration_ms": native_order.get("duration_ms"),
        "mcp_duration_ms": mcp_order.get("duration_ms"),
        "mcp_minus_native_duration_ms": round(
            float(mcp_order.get("duration_ms", 0))
            - float(native_order.get("duration_ms", 0)),
            2,
        ),
        "native_has_explicit_side_effects": native_order.get(
            "has_explicit_side_effects"
        ),
        "mcp_has_explicit_side_effects": mcp_order.get(
            "has_explicit_side_effects"
        ),
        "native_has_explicit_runtime_source": native_order.get(
            "has_explicit_runtime_source"
        ),
        "mcp_has_explicit_runtime_source": mcp_order.get(
            "has_explicit_runtime_source"
        ),
    }


def run_pending_order_test(
    args: argparse.Namespace,
    native: dict[str, Any],
    mcp: dict[str, Any],
) -> dict[str, Any]:
    if not args.include_order_test:
        return {
            "enabled": False,
            "reason": "pass --include-order-test to create pending orders",
        }

    start = time.perf_counter()
    try:
        token = load_graphql_bearer_token(args)
        order_input, input_resolution = resolve_pending_order_input(
            args,
            native,
            mcp,
            token,
        )
    except Exception as exc:
        return {
            "enabled": True,
            "success": False,
            "started_at": utc_now(),
            "duration_ms": elapsed_ms(start),
            "error": str(exc),
            "comparison": {
                "comparable": False,
                "reason": "failed to authenticate or resolve pending order input",
            },
        }

    try:
        native_order = run_native_pending_order_baseline(args, order_input, token)
    except Exception as exc:
        native_order = {
            "path": "native_graphql_pending_order_baseline",
            "success": False,
            "error": str(exc),
            "started_at": utc_now(),
        }

    try:
        mcp_order = run_mcp_pending_order_agent(args, order_input)
    except Exception as exc:
        mcp_order = {
            "path": "mcp_gateway_pending_order_tool",
            "success": False,
            "error": str(exc),
            "started_at": utc_now(),
        }

    comparison = compare_pending_order_paths(native_order, mcp_order)
    return {
        "enabled": True,
        "success": bool(comparison.get("both_pending")),
        "started_at": utc_now(),
        "duration_ms": elapsed_ms(start),
        "input": order_input,
        "input_resolution": input_resolution,
        "native_graphql": native_order,
        "mcp_gateway": mcp_order,
        "comparison": comparison,
    }


def run_native_graphql_agent(
    args: argparse.Namespace,
    api_key: str | None,
) -> dict[str, Any]:
    start = time.perf_counter()

    list_start = time.perf_counter()
    list_response = graphql_request(
        args.graphql_url,
        LIST_PRODUCTS_QUERY,
        {"first": args.top_k},
    )
    list_duration_ms = elapsed_ms(list_start)
    nodes = (
        list_response.get("data", {})
        .get("products", {})
        .get("nodes", [])
    )
    if not nodes:
        raise RuntimeError("native GraphQL returned no products")

    first_product = normalize_graphql_product(nodes[0])
    if not first_product or not first_product.get("product_id"):
        raise RuntimeError("native GraphQL first product has no product id")

    detail_start = time.perf_counter()
    detail_response = graphql_request(
        args.graphql_url,
        GET_PRODUCT_QUERY,
        {"id": first_product["product_id"]},
    )
    detail_duration_ms = elapsed_ms(detail_start)
    detail_node = detail_response.get("data", {}).get("product")
    normalized_detail = normalize_graphql_product(detail_node)

    result = {
        "path": "native_graphql",
        "success": True,
        "endpoint": args.graphql_url,
        "started_at": utc_now(),
        "duration_ms": elapsed_ms(start),
        "list_duration_ms": list_duration_ms,
        "detail_duration_ms": detail_duration_ms,
        "raw_list_response": list_response,
        "raw_detail_response": detail_response,
        "normalized_first_product": first_product,
        "normalized_detail": normalized_detail,
        "has_tool_discovery": False,
        "has_input_schema": False,
        "has_explicit_side_effects": False,
        "has_explicit_runtime_source": False,
    }
    result["agent_report"] = maybe_agent_report(
        args,
        api_key,
        build_native_graphql_prompt(result),
    )
    return result


def run_mcp_agent(
    args: argparse.Namespace,
    api_key: str | None,
) -> dict[str, Any]:
    start = time.perf_counter()

    initialize_start = time.perf_counter()
    initialize, session_id = mcp_post(
        args.mcp_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {
                    "name": "misarch-baseline-comparison-agent",
                    "version": "0.1",
                },
            },
        },
    )
    initialize_duration_ms = elapsed_ms(initialize_start)
    initialize_result = require_result(initialize)
    if not session_id:
        raise RuntimeError("MCP initialize did not return Mcp-Session-Id")

    mcp_post(
        args.mcp_url,
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
        session_id=session_id,
    )

    tools_start = time.perf_counter()
    tools_response, _ = mcp_post(
        args.mcp_url,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        },
        session_id=session_id,
    )
    tools_duration_ms = elapsed_ms(tools_start)
    tools = require_result(tools_response).get("tools", [])
    if not isinstance(tools, list):
        raise RuntimeError("tools/list did not return a tools array")

    list_start = time.perf_counter()
    product_list = call_mcp_tool(
        args.mcp_url,
        session_id,
        "list_products",
        {"top_k": args.top_k},
        3,
    )
    list_duration_ms = elapsed_ms(list_start)
    products = product_list.get("products") or []
    if not products:
        raise RuntimeError("MCP list_products returned no products")

    detail_start = time.perf_counter()
    product_detail = call_mcp_tool(
        args.mcp_url,
        session_id,
        "get_product",
        {"product_id": products[0]["product_id"]},
        4,
    )
    detail_duration_ms = elapsed_ms(detail_start)

    tool_names = [str(tool.get("name")) for tool in tools]
    has_input_schema = all(isinstance(tool.get("inputSchema"), dict) for tool in tools)
    has_explicit_side_effects = bool(
        product_list.get("side_effects") and product_detail.get("side_effects")
    )
    has_explicit_runtime_source = bool(
        product_list.get("runtime")
        and product_list.get("source_service")
        and product_detail.get("runtime")
        and product_detail.get("source_service")
    )

    result = {
        "path": "mcp_gateway",
        "success": True,
        "endpoint": args.mcp_url,
        "started_at": utc_now(),
        "duration_ms": elapsed_ms(start),
        "initialize_duration_ms": initialize_duration_ms,
        "tools_duration_ms": tools_duration_ms,
        "list_duration_ms": list_duration_ms,
        "detail_duration_ms": detail_duration_ms,
        "server_info": initialize_result.get("serverInfo"),
        "tools": tools,
        "tool_names": tool_names,
        "product_list": product_list,
        "product_detail": product_detail,
        "has_tool_discovery": True,
        "has_input_schema": has_input_schema,
        "has_explicit_side_effects": has_explicit_side_effects,
        "has_explicit_runtime_source": has_explicit_runtime_source,
    }
    result["agent_report"] = maybe_agent_report(args, api_key, build_mcp_prompt(result))
    return result


def product_from_native(result: dict[str, Any]) -> dict[str, Any] | None:
    if not result.get("success"):
        return None
    return result.get("normalized_detail") or result.get("normalized_first_product")


def product_from_mcp(result: dict[str, Any]) -> dict[str, Any] | None:
    if not result.get("success"):
        return None
    detail = result.get("product_detail") or {}
    product = detail.get("product")
    if isinstance(product, dict):
        return product
    products = (result.get("product_list") or {}).get("products") or []
    return products[0] if products else None


def compare_paths(
    native: dict[str, Any],
    mcp: dict[str, Any],
) -> dict[str, Any]:
    native_product = product_from_native(native)
    mcp_product = product_from_mcp(mcp)

    if not native_product or not mcp_product:
        return {
            "comparable": False,
            "reason": "one or both paths did not return a product",
        }

    same_product_id = native_product.get("product_id") == mcp_product.get("product_id")
    same_name = native_product.get("name") == mcp_product.get("name")
    same_price = (
        native_product.get("retail_price_cents")
        == mcp_product.get("retail_price_cents")
    )
    same_categories = native_product.get("categories") == mcp_product.get("categories")

    return {
        "comparable": True,
        "same_product_id": same_product_id,
        "same_name": same_name,
        "same_price": same_price,
        "same_categories": same_categories,
        "same_core_product_data": all(
            [same_product_id, same_name, same_price, same_categories]
        ),
        "native_product": native_product,
        "mcp_product": mcp_product,
        "native_duration_ms": native.get("duration_ms"),
        "mcp_duration_ms": mcp.get("duration_ms"),
        "mcp_minus_native_duration_ms": round(
            float(mcp.get("duration_ms", 0)) - float(native.get("duration_ms", 0)),
            2,
        ),
        "native_has_tool_discovery": native.get("has_tool_discovery"),
        "mcp_has_tool_discovery": mcp.get("has_tool_discovery"),
        "native_has_input_schema": native.get("has_input_schema"),
        "mcp_has_input_schema": mcp.get("has_input_schema"),
        "native_has_explicit_side_effects": native.get("has_explicit_side_effects"),
        "mcp_has_explicit_side_effects": mcp.get("has_explicit_side_effects"),
        "native_has_explicit_runtime_source": native.get(
            "has_explicit_runtime_source"
        ),
        "mcp_has_explicit_runtime_source": mcp.get("has_explicit_runtime_source"),
    }


def run_trial(
    args: argparse.Namespace,
    api_key: str | None,
    trial_number: int,
) -> dict[str, Any]:
    print(f"\n=== Trial {trial_number}/{args.trials} ===")

    native: dict[str, Any]
    mcp: dict[str, Any]

    print("[native] direct GraphQL agent path")
    try:
        native = run_native_graphql_agent(args, api_key)
        product = product_from_native(native) or {}
        print(
            "         ok "
            + f"product={product.get('name')} "
            + f"duration_ms={native.get('duration_ms')}"
        )
    except Exception as exc:
        native = {
            "path": "native_graphql",
            "success": False,
            "error": str(exc),
            "started_at": utc_now(),
        }
        print(f"         failed: {exc}")

    print("[mcp]    MCP gateway agent path")
    try:
        mcp = run_mcp_agent(args, api_key)
        product = product_from_mcp(mcp) or {}
        print(
            "         ok "
            + f"tools={','.join(mcp.get('tool_names', []))} "
            + f"product={product.get('name')} "
            + f"duration_ms={mcp.get('duration_ms')}"
        )
    except Exception as exc:
        mcp = {
            "path": "mcp_gateway",
            "success": False,
            "error": str(exc),
            "started_at": utc_now(),
        }
        print(f"         failed: {exc}")

    comparison = compare_paths(native, mcp)
    if comparison.get("comparable"):
        print(
            "[compare] "
            + f"same_core_product_data={comparison.get('same_core_product_data')} "
            + f"mcp_minus_native_ms={comparison.get('mcp_minus_native_duration_ms')}"
        )

    pending_order = run_pending_order_test(args, native, mcp)
    if pending_order.get("enabled"):
        pending_comparison = pending_order.get("comparison", {})
        native_order = pending_order.get("native_graphql", {})
        mcp_order = pending_order.get("mcp_gateway", {})
        if pending_order.get("error"):
            print(f"[order]  failed: {pending_order.get('error')}")
        else:
            print(
                "[order]  "
                + f"native_success={native_order.get('success')} "
                + f"mcp_success={mcp_order.get('success')} "
                + f"both_pending={pending_comparison.get('both_pending')}"
            )
            if not native_order.get("success"):
                print(f"         native failed: {native_order.get('error')}")
            if not mcp_order.get("success"):
                print(f"         mcp failed: {mcp_order.get('error')}")

    return {
        "trial": trial_number,
        "started_at": utc_now(),
        "native_graphql": native,
        "mcp_gateway": mcp,
        "comparison": comparison,
        "pending_order": pending_order,
    }


def average(values: list[float]) -> float | None:
    return round(statistics.mean(values), 2) if values else None


def build_summary(trials: list[dict[str, Any]]) -> dict[str, Any]:
    native_successes = [
        trial for trial in trials if trial.get("native_graphql", {}).get("success")
    ]
    mcp_successes = [
        trial for trial in trials if trial.get("mcp_gateway", {}).get("success")
    ]
    comparable = [
        trial
        for trial in trials
        if trial.get("comparison", {}).get("comparable")
    ]
    same_core = [
        trial
        for trial in comparable
        if trial.get("comparison", {}).get("same_core_product_data")
    ]
    pending_enabled = [
        trial
        for trial in trials
        if trial.get("pending_order", {}).get("enabled")
    ]
    native_pending_successes = [
        trial
        for trial in pending_enabled
        if trial.get("pending_order", {}).get("native_graphql", {}).get("success")
    ]
    mcp_pending_successes = [
        trial
        for trial in pending_enabled
        if trial.get("pending_order", {}).get("mcp_gateway", {}).get("success")
    ]
    pending_comparable = [
        trial
        for trial in pending_enabled
        if trial.get("pending_order", {}).get("comparison", {}).get("comparable")
    ]
    pending_both_pending = [
        trial
        for trial in pending_comparable
        if trial.get("pending_order", {}).get("comparison", {}).get("both_pending")
    ]

    native_durations = [
        float(trial["native_graphql"]["duration_ms"])
        for trial in native_successes
        if trial["native_graphql"].get("duration_ms") is not None
    ]
    mcp_durations = [
        float(trial["mcp_gateway"]["duration_ms"])
        for trial in mcp_successes
        if trial["mcp_gateway"].get("duration_ms") is not None
    ]

    return {
        "trial_count": len(trials),
        "native_success_count": len(native_successes),
        "mcp_success_count": len(mcp_successes),
        "comparable_count": len(comparable),
        "same_core_product_data_count": len(same_core),
        "pending_order_enabled_count": len(pending_enabled),
        "native_pending_order_success_count": len(native_pending_successes),
        "mcp_pending_order_success_count": len(mcp_pending_successes),
        "pending_order_comparable_count": len(pending_comparable),
        "pending_order_both_pending_count": len(pending_both_pending),
        "native_avg_duration_ms": average(native_durations),
        "mcp_avg_duration_ms": average(mcp_durations),
        "interpretation": (
            "GraphQL and MCP should return the same core MiSArch product data. "
            "MCP adds agent-facing metadata and protocol-level tool discovery. "
            "Pending-order comparisons are disabled unless explicitly enabled "
            "because they create shopping cart items and pending orders."
        ),
    }


def write_results(
    args: argparse.Namespace,
    trials: list[dict[str, Any]],
    summary: dict[str, Any],
) -> tuple[pathlib.Path, pathlib.Path]:
    results_dir = pathlib.Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = args.output_prefix or f"agent_comparison_{timestamp}"
    json_path = results_dir / f"{prefix}.json"
    csv_path = results_dir / f"{prefix}.csv"

    payload = {
        "created_at": utc_now(),
        "config": {
            "graphql_url": args.graphql_url,
            "mcp_url": args.mcp_url,
            "model_base_url": args.model_base_url,
            "model": args.model,
            "trials": args.trials,
            "top_k": args.top_k,
            "skip_llm": args.skip_llm,
            "include_order_test": args.include_order_test,
            "order_quantity": args.order_quantity,
            "order_product_variant_id": args.order_product_variant_id,
            "order_user_id": args.order_user_id,
            "order_shipment_method_id": args.order_shipment_method_id,
            "order_shipment_address_id": args.order_shipment_address_id,
            "order_invoice_address_id": args.order_invoice_address_id,
            "order_payment_information_id": args.order_payment_information_id,
            "order_coupon_ids": args.order_coupon_ids,
            "graphql_bearer_token_configured": bool(args.graphql_bearer_token),
            "keycloak_token_url_configured": bool(args.keycloak_token_url),
        },
        "summary": summary,
        "trials": trials,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "trial",
                "native_success",
                "mcp_success",
                "same_core_product_data",
                "same_product_id",
                "same_name",
                "same_price",
                "native_duration_ms",
                "mcp_duration_ms",
                "mcp_minus_native_duration_ms",
                "native_product_name",
                "mcp_product_name",
                "mcp_tools",
                "native_has_tool_discovery",
                "mcp_has_tool_discovery",
                "native_has_explicit_side_effects",
                "mcp_has_explicit_side_effects",
                "native_has_explicit_runtime_source",
                "mcp_has_explicit_runtime_source",
                "native_agent_report_ok",
                "native_agent_report_skipped",
                "mcp_agent_report_ok",
                "mcp_agent_report_skipped",
                "pending_order_enabled",
                "native_pending_order_success",
                "mcp_pending_order_success",
                "pending_order_comparable",
                "pending_order_same_status",
                "pending_order_both_pending",
                "native_pending_order_status",
                "mcp_pending_order_status",
                "native_pending_order_duration_ms",
                "mcp_pending_order_duration_ms",
                "pending_order_mcp_minus_native_duration_ms",
            ],
        )
        writer.writeheader()
        for trial in trials:
            native = trial.get("native_graphql", {})
            mcp = trial.get("mcp_gateway", {})
            comparison = trial.get("comparison", {})
            pending_order = trial.get("pending_order", {})
            native_pending = pending_order.get("native_graphql", {})
            mcp_pending = pending_order.get("mcp_gateway", {})
            pending_comparison = pending_order.get("comparison", {})
            native_product = product_from_native(native) or {}
            mcp_product = product_from_mcp(mcp) or {}
            writer.writerow(
                {
                    "trial": trial.get("trial"),
                    "native_success": native.get("success"),
                    "mcp_success": mcp.get("success"),
                    "same_core_product_data": comparison.get("same_core_product_data"),
                    "same_product_id": comparison.get("same_product_id"),
                    "same_name": comparison.get("same_name"),
                    "same_price": comparison.get("same_price"),
                    "native_duration_ms": native.get("duration_ms"),
                    "mcp_duration_ms": mcp.get("duration_ms"),
                    "mcp_minus_native_duration_ms": comparison.get(
                        "mcp_minus_native_duration_ms"
                    ),
                    "native_product_name": native_product.get("name"),
                    "mcp_product_name": mcp_product.get("name"),
                    "mcp_tools": ",".join(mcp.get("tool_names", [])),
                    "native_has_tool_discovery": native.get("has_tool_discovery"),
                    "mcp_has_tool_discovery": mcp.get("has_tool_discovery"),
                    "native_has_explicit_side_effects": native.get(
                        "has_explicit_side_effects"
                    ),
                    "mcp_has_explicit_side_effects": mcp.get(
                        "has_explicit_side_effects"
                    ),
                    "native_has_explicit_runtime_source": native.get(
                        "has_explicit_runtime_source"
                    ),
                    "mcp_has_explicit_runtime_source": mcp.get(
                        "has_explicit_runtime_source"
                    ),
                    "native_agent_report_ok": (
                        native.get("agent_report") or {}
                    ).get("ok"),
                    "native_agent_report_skipped": (
                        native.get("agent_report") or {}
                    ).get("skipped"),
                    "mcp_agent_report_ok": (mcp.get("agent_report") or {}).get("ok"),
                    "mcp_agent_report_skipped": (
                        mcp.get("agent_report") or {}
                    ).get("skipped"),
                    "pending_order_enabled": pending_order.get("enabled"),
                    "native_pending_order_success": native_pending.get("success"),
                    "mcp_pending_order_success": mcp_pending.get("success"),
                    "pending_order_comparable": pending_comparison.get("comparable"),
                    "pending_order_same_status": pending_comparison.get(
                        "same_order_status"
                    ),
                    "pending_order_both_pending": pending_comparison.get(
                        "both_pending"
                    ),
                    "native_pending_order_status": pending_comparison.get(
                        "native_order_status"
                    ),
                    "mcp_pending_order_status": pending_comparison.get(
                        "mcp_order_status"
                    ),
                    "native_pending_order_duration_ms": native_pending.get(
                        "duration_ms"
                    ),
                    "mcp_pending_order_duration_ms": mcp_pending.get("duration_ms"),
                    "pending_order_mcp_minus_native_duration_ms": (
                        pending_comparison.get("mcp_minus_native_duration_ms")
                    ),
                }
            )

    return json_path, csv_path


def run(args: argparse.Namespace) -> None:
    api_key = None if args.skip_llm else load_api_key()
    trials = [run_trial(args, api_key, trial) for trial in range(1, args.trials + 1)]
    summary = build_summary(trials)
    json_path, csv_path = write_results(args, trials, summary)

    print("\n=== Summary ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nSaved JSON: {json_path}")
    print(f"Saved CSV:  {csv_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare native MiSArch GraphQL access with MCP gateway access "
            "for agent-facing interoperability."
        )
    )
    parser.add_argument(
        "--graphql-url",
        default=os.environ.get("MISARCH_GRAPHQL_URL", DEFAULT_GRAPHQL_URL),
    )
    parser.add_argument("--mcp-url", default=os.environ.get("MISARCH_MCP_URL", DEFAULT_MCP_URL))
    parser.add_argument(
        "--model-base-url",
        default=os.environ.get("OPENAI_BASE_URL", DEFAULT_MODEL_BASE_URL),
    )
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=2)
    parser.add_argument("--results-dir", default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--output-prefix", default="")
    parser.add_argument(
        "--include-order-test",
        action="store_true",
        help=(
            "Also compare create_pending_order against raw GraphQL. "
            "This creates shopping cart items and pending orders."
        ),
    )
    parser.add_argument("--order-quantity", type=int, default=1)
    parser.add_argument("--order-product-variant-id", default="")
    parser.add_argument("--order-user-id", default="")
    parser.add_argument("--order-shipment-method-id", default="")
    parser.add_argument("--order-shipment-address-id", default="")
    parser.add_argument("--order-invoice-address-id", default="")
    parser.add_argument("--order-payment-information-id", default="")
    parser.add_argument(
        "--order-coupon-ids",
        default="",
        help="Comma-separated coupon UUIDs for the pending order item.",
    )
    parser.add_argument(
        "--graphql-bearer-token",
        default=os.environ.get("MISARCH_GRAPHQL_BEARER_TOKEN", ""),
        help=(
            "Bearer token for raw GraphQL write/discovery calls. "
            "Alternatively configure Keycloak arguments."
        ),
    )
    parser.add_argument(
        "--keycloak-token-url",
        default=default_keycloak_token_url(),
        help=(
            "Keycloak token endpoint used when --include-order-test is enabled "
            "and --graphql-bearer-token is not provided."
        ),
    )
    parser.add_argument(
        "--keycloak-client-id",
        default=(
            os.environ.get("MISARCH_KEYCLOAK_CLIENT_ID")
            or os.environ.get("CLIENT_ID")
            or DEFAULT_KEYCLOAK_CLIENT_ID
        ),
    )
    parser.add_argument(
        "--keycloak-username",
        default=(
            os.environ.get("MISARCH_KEYCLOAK_USERNAME")
            or os.environ.get("GATLING_USERNAME")
            or DEFAULT_KEYCLOAK_USERNAME
        ),
    )
    parser.add_argument(
        "--keycloak-password",
        default=(
            os.environ.get("MISARCH_KEYCLOAK_PASSWORD")
            or os.environ.get("GATLING_PASSWORD")
            or DEFAULT_KEYCLOAK_PASSWORD
        ),
    )
    parser.add_argument(
        "--keycloak-grant-type",
        default=os.environ.get("GRANT_TYPE", "password"),
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Run GraphQL and MCP calls only; skip model-generated agent reports.",
    )
    args = parser.parse_args()

    if args.trials < 1:
        print("ERROR: --trials must be >= 1", file=sys.stderr)
        return 1
    if args.top_k < 1:
        print("ERROR: --top-k must be >= 1", file=sys.stderr)
        return 1
    if args.order_quantity < 1:
        print("ERROR: --order-quantity must be >= 1", file=sys.stderr)
        return 1
    if args.order_quantity > 3:
        print("ERROR: --order-quantity must be <= 3", file=sys.stderr)
        return 1
    if args.include_order_test and not (
        args.graphql_bearer_token or args.keycloak_token_url
    ):
        print(
            "ERROR: --include-order-test requires --graphql-bearer-token or "
            "--keycloak-token-url/MISARCH_KEYCLOAK_TOKEN_URL",
            file=sys.stderr,
        )
        return 1

    try:
        run(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
