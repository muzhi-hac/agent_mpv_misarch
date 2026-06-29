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
DEFAULT_MODEL_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")
DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4")
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

GRAPHQL_AGENT_SCHEMA_DOC = """
MiSArch catalog GraphQL documentation excerpt for read-only product lookup:

scalar UUID

type Query {
  products(first: Int!): ProductConnection!
  product(id: UUID!): Product
}

type ProductConnection {
  nodes: [Product!]!
}

type Product {
  id: UUID!
  defaultVariant: ProductVariant
  categories(first: Int!): CategoryConnection!
}

type ProductVariant {
  id: UUID!
  currentVersion: ProductVariantVersion
}

type ProductVariantVersion {
  name: String
  description: String
  retailPrice: Int
}

type CategoryConnection {
  nodes: [Category!]!
}

type Category {
  name: String!
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


def extract_json_object(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        payload = json.loads(raw[start : end + 1])

    if not isinstance(payload, dict):
        raise RuntimeError(f"model output JSON is not an object: {payload}")
    return payload


def require_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"model output is missing string field {key!r}: {payload}")
    return value.strip()


def safe_graphql_query(query: str, label: str) -> None:
    lower_query = query.lower()
    if "mutation" in lower_query or "subscription" in lower_query:
        raise RuntimeError(f"{label} must be read-only query, got: {query[:160]}")
    if "query" not in lower_query:
        raise RuntimeError(f"{label} must contain a GraphQL query operation")


def build_agent_generated_graphql_generation_prompt(
    top_k: int,
    doc_level: str,
) -> str:
    base_prompt = (
        "You are testing whether an autonomous agent can use a native GraphQL API "
        "without receiving pre-written queries.\n"
        "Generate two read-only GraphQL queries: one to list products, and one to "
        "fetch product details by UUID.\n"
        "The queries should return enough fields to compare product_id, variant_id, "
        "name, description, retailPrice, and category names.\n\n"
        "Return ONLY valid JSON with this exact shape:\n"
        "{\n"
        '  "list_query": "...",\n'
        '  "list_variables": {"first": 2},\n'
        '  "detail_query": "...",\n'
        '  "detail_variables": {"id": "$PRODUCT_ID_FROM_LIST"},\n'
        '  "notes": "short explanation"\n'
        "}\n\n"
        f"Use first={top_k} in list_variables.\n"
    )

    if doc_level == "minimal":
        return (
            base_prompt
            + "\nNo schema documentation is available. Infer the GraphQL shape from "
            "the task name only. This is intentionally difficult and failures are "
            "valid experimental evidence.\n"
        )

    return base_prompt + "\nUse only this documentation excerpt:\n\n" + GRAPHQL_AGENT_SCHEMA_DOC


def parse_agent_generated_graphql_plan(text: str, top_k: int) -> dict[str, Any]:
    payload = extract_json_object(text)
    list_query = require_string(payload, "list_query")
    detail_query = require_string(payload, "detail_query")
    safe_graphql_query(list_query, "list_query")
    safe_graphql_query(detail_query, "detail_query")

    list_variables = payload.get("list_variables")
    if not isinstance(list_variables, dict):
        list_variables = {}
    if not isinstance(list_variables.get("first"), int):
        list_variables["first"] = top_k

    detail_variables = payload.get("detail_variables")
    if not isinstance(detail_variables, dict):
        detail_variables = {}

    return {
        "list_query": list_query,
        "list_variables": list_variables,
        "detail_query": detail_query,
        "detail_variables_template": detail_variables,
        "notes": payload.get("notes"),
    }


def build_fixed_graphql_controller_prompt(top_k: int) -> str:
    return (
        "You are an agent controller. Task: read real MiSArch catalog product data.\n"
        "You are NOT allowed to write GraphQL. You have exactly one executor:\n"
        "- fixed_graphql_catalog_lookup: executes pre-written safe GraphQL queries "
        "to list products and fetch the first product detail.\n\n"
        "Choose the executor and arguments. Return ONLY valid JSON with this shape:\n"
        "{\n"
        '  "executor": "fixed_graphql_catalog_lookup",\n'
        f'  "arguments": {{"top_k": {top_k}}},\n'
        '  "rationale": "short explanation"\n'
        "}\n"
    )


def parse_fixed_graphql_decision(text: str, top_k: int) -> dict[str, Any]:
    payload = extract_json_object(text)
    executor = require_string(payload, "executor")
    if executor != "fixed_graphql_catalog_lookup":
        raise RuntimeError(f"unexpected fixed GraphQL executor: {executor}")
    arguments = payload.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    selected_top_k = arguments.get("top_k")
    if not isinstance(selected_top_k, int) or selected_top_k < 1:
        selected_top_k = top_k
    arguments["top_k"] = selected_top_k
    return {
        "executor": executor,
        "arguments": arguments,
        "rationale": payload.get("rationale"),
    }


def build_mcp_controller_prompt(top_k: int, tools: list[Any]) -> str:
    compact_tools = [
        {
            "name": tool.get("name"),
            "description": tool.get("description"),
            "inputSchema": tool.get("inputSchema"),
        }
        for tool in tools
        if isinstance(tool, dict)
    ]
    return (
        "You are an agent controller. Task: read real MiSArch catalog product data "
        "through MCP, using tool discovery and tool calls.\n"
        "You must select MCP tools from the discovered tool list below. "
        "Do not write GraphQL.\n\n"
        "Return ONLY valid JSON with this shape:\n"
        "{\n"
        '  "tool_calls": [\n'
        f'    {{"name": "list_products", "arguments": {{"top_k": {top_k}}}}},\n'
        '    {"name": "get_product", "arguments": {"product_id": "$FIRST_PRODUCT_ID_FROM_LIST"}}\n'
        "  ],\n"
        '  "rationale": "short explanation"\n'
        "}\n\n"
        f"Discovered MCP tools:\n{json.dumps(compact_tools, ensure_ascii=False, indent=2)}"
    )


def parse_mcp_tool_plan(text: str, top_k: int) -> dict[str, Any]:
    payload = extract_json_object(text)
    calls = payload.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        raise RuntimeError(f"MCP controller output has no tool_calls: {payload}")

    normalized_calls: list[dict[str, Any]] = []
    for call in calls:
        if not isinstance(call, dict):
            raise RuntimeError(f"MCP tool call is not an object: {call}")
        name = require_string(call, "name")
        arguments = call.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        normalized_calls.append({"name": name, "arguments": arguments})

    tool_names = [call["name"] for call in normalized_calls]
    if "list_products" not in tool_names:
        raise RuntimeError(f"MCP plan did not include list_products: {tool_names}")
    if "get_product" not in tool_names:
        raise RuntimeError(f"MCP plan did not include get_product: {tool_names}")

    for call in normalized_calls:
        if call["name"] == "list_products":
            selected_top_k = call["arguments"].get("top_k")
            if not isinstance(selected_top_k, int) or selected_top_k < 1:
                call["arguments"]["top_k"] = top_k

    return {
        "tool_calls": normalized_calls,
        "rationale": payload.get("rationale"),
    }


def llm_controller_decision(
    args: argparse.Namespace,
    api_key: str | None,
    prompt: str,
    parser: Any,
) -> dict[str, Any]:
    if not api_key:
        raise RuntimeError("LLM controller requires an API key")
    start = time.perf_counter()
    raw_output = responses_api_call(args.model_base_url, api_key, args.model, prompt)
    parsed = parser(raw_output)
    return {
        "raw_output": raw_output,
        "decision": parsed,
        "duration_ms": elapsed_ms(start),
    }


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


def graphql_request_raw(
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
    return response


def graphql_errors_text(response: dict[str, Any]) -> str:
    errors = response.get("errors")
    if not errors:
        return ""
    return json.dumps(errors, ensure_ascii=False)


def first_present(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def connection_nodes(value: Any) -> list[Any]:
    if isinstance(value, dict):
        nodes = value.get("nodes")
        return nodes if isinstance(nodes, list) else []
    if isinstance(value, list):
        return value
    return []


def category_names(category_nodes: list[Any]) -> list[str]:
    names: list[str] = []
    for category in category_nodes:
        if not isinstance(category, dict):
            continue
        name = first_present(category, ("name", "category_name", "categoryName"))
        if isinstance(name, str) and name.strip():
            names.append(name)
    return names


def normalize_graphql_product(node: dict[str, Any] | None) -> dict[str, Any] | None:
    if not node:
        return None

    variant = first_present(
        node,
        ("defaultVariant", "default_variant", "variant", "productVariant"),
    )
    if not isinstance(variant, dict):
        variant = {}

    version = first_present(
        variant,
        ("currentVersion", "current_version", "version", "productVersion"),
    )
    if not isinstance(version, dict):
        version = {}

    category_nodes = connection_nodes(node.get("categories"))

    return {
        "product_id": first_present(node, ("id", "product_id", "productId")),
        "variant_id": first_present(variant, ("id", "variant_id", "variantId")),
        "name": first_present(version, ("name", "product_name", "productName")),
        "description": version.get("description"),
        "retail_price_cents": first_present(
            version,
            ("retailPrice", "retail_price", "retailPriceCents", "retail_price_cents"),
        ),
        "currency": "EUR",
        "categories": category_names(category_nodes),
    }


def missing_product_fields(product: dict[str, Any] | None) -> list[str]:
    if not product:
        return ["product"]

    required = (
        "product_id",
        "variant_id",
        "name",
        "retail_price_cents",
        "categories",
    )
    missing: list[str] = []
    for field in required:
        value = product.get(field)
        if value is None or value == "" or value == []:
            missing.append(field)
    return missing


def agent_generated_failure_result(
    start: float,
    stage: str,
    error: str,
    doc_level: str = "schema",
    raw_model_output: str | None = None,
    generated_plan: dict[str, Any] | None = None,
    raw_list_response: dict[str, Any] | None = None,
    raw_detail_response: dict[str, Any] | None = None,
    normalized_first_product: dict[str, Any] | None = None,
    normalized_detail: dict[str, Any] | None = None,
    generation_duration_ms: float | None = None,
    list_duration_ms: float | None = None,
    detail_duration_ms: float | None = None,
) -> dict[str, Any]:
    return {
        "path": "agent_generated_graphql",
        "enabled": True,
        "success": False,
        "failure_stage": stage,
        "error": error,
        "started_at": utc_now(),
        "duration_ms": elapsed_ms(start),
        "generation_duration_ms": generation_duration_ms,
        "list_duration_ms": list_duration_ms,
        "detail_duration_ms": detail_duration_ms,
        "raw_model_output": raw_model_output,
        "generated_plan": generated_plan,
        "raw_list_response": raw_list_response,
        "raw_detail_response": raw_detail_response,
        "normalized_first_product": normalized_first_product,
        "normalized_detail": normalized_detail,
        "has_tool_discovery": False,
        "has_input_schema": False,
        "has_explicit_side_effects": False,
        "has_explicit_runtime_source": False,
        "agent_generated_query": True,
        "llm_controller_used": True,
        "schema_context_provided": doc_level == "schema",
        "doc_level": doc_level,
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
        "You are an external agent tester. This time you access the MiSArch native GraphQL API directly.\n"
        "Answer based only on the JSON evidence below, do not make things up. Briefly explain in English:\n"
        "1. whether real products were read successfully;\n"
        "2. the structural characteristics of the data returned by native GraphQL;\n"
        "3. whether it provides tool discovery, side effects, runtime/source_service;\n"
        "4. the pros and cons as an agent baseline.\n\n"
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
        "You are an external agent tester. This time you access MiSArch through the MCP gateway.\n"
        "Answer based only on the JSON evidence below, do not make things up. Briefly explain in English:\n"
        "1. which MCP tools the agent discovered;\n"
        "2. whether real products were read successfully;\n"
        "3. whether runtime/source_service and side effects are explicit;\n"
        "4. the pros and cons as an agent-facing interface.\n\n"
        f"JSON evidence:\n{json.dumps(evidence, ensure_ascii=False, indent=2)}"
    )


def maybe_agent_report(
    args: argparse.Namespace,
    api_key: str | None,
    prompt: str,
) -> dict[str, Any]:
    if args.skip_llm or args.skip_agent_reports:
        return {
            "ok": True,
            "skipped": True,
            "duration_ms": 0.0,
            "text": "LLM report skipped by --skip-llm or --skip-agent-reports.",
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
    controller: dict[str, Any] | None = None

    if args.use_llm_controller:
        controller = llm_controller_decision(
            args,
            api_key,
            build_fixed_graphql_controller_prompt(args.top_k),
            lambda raw: parse_fixed_graphql_decision(raw, args.top_k),
        )

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
        "llm_controller_used": args.use_llm_controller,
        "llm_controller": controller,
    }
    result["agent_report"] = maybe_agent_report(
        args,
        api_key,
        build_native_graphql_prompt(result),
    )
    return result


def run_agent_generated_graphql_agent(
    args: argparse.Namespace,
    api_key: str | None,
) -> dict[str, Any]:
    if not api_key:
        raise RuntimeError("agent-generated GraphQL baseline requires an API key")

    start = time.perf_counter()
    raw_model_output: str | None = None
    plan: dict[str, Any] | None = None
    generation_duration_ms: float | None = None
    list_duration_ms: float | None = None
    detail_duration_ms: float | None = None

    def fail(stage: str, error: str, **evidence: Any) -> dict[str, Any]:
        return agent_generated_failure_result(
            start,
            stage,
            error,
            doc_level=args.agent_generated_graphql_doc_level,
            **evidence,
        )

    generation_prompt = build_agent_generated_graphql_generation_prompt(
        args.top_k,
        args.agent_generated_graphql_doc_level,
    )
    generation_start = time.perf_counter()
    try:
        raw_model_output = responses_api_call(
            args.model_base_url,
            api_key,
            args.model,
            generation_prompt,
        )
        generation_duration_ms = elapsed_ms(generation_start)
    except Exception as exc:
        return fail(
            "model_generation",
            str(exc),
        )

    try:
        plan = parse_agent_generated_graphql_plan(raw_model_output, args.top_k)
    except Exception as exc:
        return fail(
            "model_output_parse",
            str(exc),
            raw_model_output=raw_model_output,
            generation_duration_ms=generation_duration_ms,
        )

    list_start = time.perf_counter()
    try:
        list_response = graphql_request_raw(
            args.graphql_url,
            plan["list_query"],
            plan["list_variables"],
        )
    except Exception as exc:
        return fail(
            "list_query_http",
            str(exc),
            raw_model_output=raw_model_output,
            generated_plan=plan,
            generation_duration_ms=generation_duration_ms,
        )
    list_duration_ms = elapsed_ms(list_start)
    if list_response.get("errors"):
        return fail(
            "list_query_graphql_errors",
            graphql_errors_text(list_response),
            raw_model_output=raw_model_output,
            generated_plan=plan,
            raw_list_response=list_response,
            generation_duration_ms=generation_duration_ms,
            list_duration_ms=list_duration_ms,
        )

    data = list_response.get("data")
    if not isinstance(data, dict):
        return fail(
            "list_response_shape",
            "GraphQL list response has no data object",
            raw_model_output=raw_model_output,
            generated_plan=plan,
            raw_list_response=list_response,
            generation_duration_ms=generation_duration_ms,
            list_duration_ms=list_duration_ms,
        )

    nodes = (
        data
        .get("products", {})
        .get("nodes", [])
    )
    if not nodes:
        return fail(
            "list_response_shape",
            "agent-generated GraphQL returned no products at data.products.nodes",
            raw_model_output=raw_model_output,
            generated_plan=plan,
            raw_list_response=list_response,
            generation_duration_ms=generation_duration_ms,
            list_duration_ms=list_duration_ms,
        )

    first_product = normalize_graphql_product(nodes[0])
    missing_first_fields = missing_product_fields(first_product)
    if "product_id" in missing_first_fields:
        return fail(
            "list_response_shape",
            "agent-generated GraphQL list result has no usable product_id",
            raw_model_output=raw_model_output,
            generated_plan=plan,
            raw_list_response=list_response,
            normalized_first_product=first_product,
            generation_duration_ms=generation_duration_ms,
            list_duration_ms=list_duration_ms,
        )

    detail_variables = dict(plan["detail_variables_template"])
    detail_variables["id"] = first_product["product_id"]
    executable_plan = {
        **plan,
        "detail_variables": detail_variables,
        "doc_level": args.agent_generated_graphql_doc_level,
    }

    detail_start = time.perf_counter()
    try:
        detail_response = graphql_request_raw(
            args.graphql_url,
            plan["detail_query"],
            detail_variables,
        )
    except Exception as exc:
        return fail(
            "detail_query_http",
            str(exc),
            raw_model_output=raw_model_output,
            generated_plan=executable_plan,
            raw_list_response=list_response,
            normalized_first_product=first_product,
            generation_duration_ms=generation_duration_ms,
            list_duration_ms=list_duration_ms,
        )
    detail_duration_ms = elapsed_ms(detail_start)
    if detail_response.get("errors"):
        return fail(
            "detail_query_graphql_errors",
            graphql_errors_text(detail_response),
            raw_model_output=raw_model_output,
            generated_plan=executable_plan,
            raw_list_response=list_response,
            raw_detail_response=detail_response,
            normalized_first_product=first_product,
            generation_duration_ms=generation_duration_ms,
            list_duration_ms=list_duration_ms,
            detail_duration_ms=detail_duration_ms,
        )

    detail_data = detail_response.get("data")
    if not isinstance(detail_data, dict):
        return fail(
            "detail_response_shape",
            "GraphQL detail response has no data object",
            raw_model_output=raw_model_output,
            generated_plan=executable_plan,
            raw_list_response=list_response,
            raw_detail_response=detail_response,
            normalized_first_product=first_product,
            generation_duration_ms=generation_duration_ms,
            list_duration_ms=list_duration_ms,
            detail_duration_ms=detail_duration_ms,
        )

    detail_node = detail_data.get("product")
    normalized_detail = normalize_graphql_product(detail_node)
    missing_detail_fields = missing_product_fields(normalized_detail)
    if missing_detail_fields:
        return fail(
            "detail_response_shape",
            "agent-generated GraphQL detail result is missing fields: "
            + ", ".join(missing_detail_fields),
            raw_model_output=raw_model_output,
            generated_plan=executable_plan,
            raw_list_response=list_response,
            raw_detail_response=detail_response,
            normalized_first_product=first_product,
            normalized_detail=normalized_detail,
            generation_duration_ms=generation_duration_ms,
            list_duration_ms=list_duration_ms,
            detail_duration_ms=detail_duration_ms,
        )

    result = {
        "path": "agent_generated_graphql",
        "enabled": True,
        "success": True,
        "endpoint": args.graphql_url,
        "started_at": utc_now(),
        "duration_ms": elapsed_ms(start),
        "generation_duration_ms": generation_duration_ms,
        "list_duration_ms": list_duration_ms,
        "detail_duration_ms": detail_duration_ms,
        "raw_model_output": raw_model_output,
        "generated_plan": executable_plan,
        "raw_list_response": list_response,
        "raw_detail_response": detail_response,
        "normalized_first_product": first_product,
        "normalized_detail": normalized_detail,
        "has_tool_discovery": False,
        "has_input_schema": False,
        "has_explicit_side_effects": False,
        "has_explicit_runtime_source": False,
        "agent_generated_query": True,
        "llm_controller_used": True,
        "schema_context_provided": args.agent_generated_graphql_doc_level == "schema",
        "doc_level": args.agent_generated_graphql_doc_level,
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
    controller: dict[str, Any] | None = None

    initialize_start = time.perf_counter()
    initialize, session_id = mcp_post(
        args.mcp_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
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

    if args.use_llm_controller:
        controller = llm_controller_decision(
            args,
            api_key,
            build_mcp_controller_prompt(args.top_k, tools),
            lambda raw: parse_mcp_tool_plan(raw, args.top_k),
        )
        planned_calls = controller["decision"]["tool_calls"]
    else:
        planned_calls = [
            {
                "name": "list_products",
                "arguments": {"top_k": args.top_k},
            },
            {
                "name": "get_product",
                "arguments": {"product_id": "$FIRST_PRODUCT_ID_FROM_LIST"},
            },
        ]

    list_call = next(
        (call for call in planned_calls if call.get("name") == "list_products"),
        None,
    )
    if not isinstance(list_call, dict):
        raise RuntimeError(f"MCP plan has no list_products call: {planned_calls}")
    list_arguments = list_call.get("arguments")
    if not isinstance(list_arguments, dict):
        list_arguments = {"top_k": args.top_k}

    list_start = time.perf_counter()
    product_list = call_mcp_tool(
        args.mcp_url,
        session_id,
        "list_products",
        list_arguments,
        3,
    )
    list_duration_ms = elapsed_ms(list_start)
    products = product_list.get("products") or []
    if not products:
        raise RuntimeError("MCP list_products returned no products")

    detail_call = next(
        (call for call in planned_calls if call.get("name") == "get_product"),
        None,
    )
    if not isinstance(detail_call, dict):
        raise RuntimeError(f"MCP plan has no get_product call: {planned_calls}")
    detail_arguments = detail_call.get("arguments")
    if not isinstance(detail_arguments, dict):
        detail_arguments = {}
    if detail_arguments.get("product_id") == "$FIRST_PRODUCT_ID_FROM_LIST":
        detail_arguments = {
            **detail_arguments,
            "product_id": products[0]["product_id"],
        }
    if not detail_arguments.get("product_id"):
        detail_arguments = {
            **detail_arguments,
            "product_id": products[0]["product_id"],
        }

    detail_start = time.perf_counter()
    product_detail = call_mcp_tool(
        args.mcp_url,
        session_id,
        "get_product",
        detail_arguments,
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
        "llm_controller_used": args.use_llm_controller,
        "llm_controller": controller,
        "planned_tool_calls": planned_calls,
        "executed_tool_calls": [
            {"name": "list_products", "arguments": list_arguments},
            {"name": "get_product", "arguments": detail_arguments},
        ],
    }
    result["agent_report"] = maybe_agent_report(args, api_key, build_mcp_prompt(result))
    return result


def product_from_native(result: dict[str, Any]) -> dict[str, Any] | None:
    if not result.get("success"):
        return None
    return result.get("normalized_detail") or result.get("normalized_first_product")


def product_from_agent_generated(result: dict[str, Any]) -> dict[str, Any] | None:
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


def compare_agent_generated_graphql(
    native: dict[str, Any],
    generated: dict[str, Any],
) -> dict[str, Any]:
    native_product = product_from_native(native)
    generated_product = product_from_agent_generated(generated)

    if not native_product or not generated_product:
        return {
            "comparable": False,
            "reason": "fixed or agent-generated GraphQL did not return a product",
        }

    same_product_id = (
        native_product.get("product_id") == generated_product.get("product_id")
    )
    same_name = native_product.get("name") == generated_product.get("name")
    same_price = (
        native_product.get("retail_price_cents")
        == generated_product.get("retail_price_cents")
    )
    same_categories = (
        native_product.get("categories") == generated_product.get("categories")
    )

    return {
        "comparable": True,
        "same_product_id": same_product_id,
        "same_name": same_name,
        "same_price": same_price,
        "same_categories": same_categories,
        "same_core_product_data": all(
            [same_product_id, same_name, same_price, same_categories]
        ),
        "fixed_graphql_product": native_product,
        "agent_generated_graphql_product": generated_product,
        "fixed_graphql_duration_ms": native.get("duration_ms"),
        "agent_generated_graphql_duration_ms": generated.get("duration_ms"),
        "generation_duration_ms": generated.get("generation_duration_ms"),
    }


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
    agent_generated: dict[str, Any]
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

    if args.include_agent_generated_graphql:
        print("[agent]  agent-generated GraphQL baseline")
        try:
            agent_generated = run_agent_generated_graphql_agent(args, api_key)
            if agent_generated.get("success"):
                product = product_from_agent_generated(agent_generated) or {}
                print(
                    "         ok "
                    + f"product={product.get('name')} "
                    + f"duration_ms={agent_generated.get('duration_ms')} "
                    + f"generation_ms={agent_generated.get('generation_duration_ms')}"
                )
            else:
                print(
                    "         failed "
                    + f"stage={agent_generated.get('failure_stage')} "
                    + f"error={agent_generated.get('error')}"
                )
        except Exception as exc:
            agent_generated = {
                "path": "agent_generated_graphql",
                "enabled": True,
                "success": False,
                "failure_stage": "unexpected_exception",
                "error": str(exc),
                "started_at": utc_now(),
            }
            print(f"         failed: {exc}")
    else:
        agent_generated = {
            "path": "agent_generated_graphql",
            "enabled": False,
            "success": False,
            "skipped": True,
            "reason": "disabled; pass --include-agent-generated-graphql to enable",
        }

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

    agent_generated_comparison = compare_agent_generated_graphql(
        native,
        agent_generated,
    )
    if agent_generated_comparison.get("comparable"):
        print(
            "[compare-agent] "
            + "same_core_product_data="
            + f"{agent_generated_comparison.get('same_core_product_data')}"
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
        "agent_generated_graphql": agent_generated,
        "mcp_gateway": mcp,
        "comparison": comparison,
        "agent_generated_comparison": agent_generated_comparison,
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
    agent_generated_enabled = [
        trial
        for trial in trials
        if trial.get("agent_generated_graphql", {}).get("enabled")
    ]
    agent_generated_successes = [
        trial
        for trial in agent_generated_enabled
        if trial.get("agent_generated_graphql", {}).get("success")
    ]
    agent_generated_comparable = [
        trial
        for trial in agent_generated_enabled
        if trial.get("agent_generated_comparison", {}).get("comparable")
    ]
    agent_generated_same_core = [
        trial
        for trial in agent_generated_comparable
        if trial.get("agent_generated_comparison", {}).get("same_core_product_data")
    ]
    agent_generated_failure_stage_counts: dict[str, int] = {}
    for trial in agent_generated_enabled:
        agent_result = trial.get("agent_generated_graphql", {})
        if agent_result.get("success"):
            continue
        stage = str(agent_result.get("failure_stage") or "unknown")
        agent_generated_failure_stage_counts[stage] = (
            agent_generated_failure_stage_counts.get(stage, 0) + 1
        )
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
    agent_generated_durations = [
        float(trial["agent_generated_graphql"]["duration_ms"])
        for trial in agent_generated_successes
        if trial["agent_generated_graphql"].get("duration_ms") is not None
    ]
    agent_generated_generation_durations = [
        float(trial["agent_generated_graphql"]["generation_duration_ms"])
        for trial in agent_generated_successes
        if trial["agent_generated_graphql"].get("generation_duration_ms") is not None
    ]

    return {
        "trial_count": len(trials),
        "llm_controller_enabled": any(
            bool(trial.get("native_graphql", {}).get("llm_controller_used"))
            or bool(trial.get("mcp_gateway", {}).get("llm_controller_used"))
            for trial in trials
        ),
        "native_success_count": len(native_successes),
        "mcp_success_count": len(mcp_successes),
        "agent_generated_graphql_enabled_count": len(agent_generated_enabled),
        "agent_generated_graphql_success_count": len(agent_generated_successes),
        "agent_generated_graphql_comparable_count": len(agent_generated_comparable),
        "agent_generated_graphql_same_core_product_data_count": len(
            agent_generated_same_core
        ),
        "agent_generated_graphql_failure_stage_counts": (
            agent_generated_failure_stage_counts
        ),
        "comparable_count": len(comparable),
        "same_core_product_data_count": len(same_core),
        "pending_order_enabled_count": len(pending_enabled),
        "native_pending_order_success_count": len(native_pending_successes),
        "mcp_pending_order_success_count": len(mcp_pending_successes),
        "pending_order_comparable_count": len(pending_comparable),
        "pending_order_both_pending_count": len(pending_both_pending),
        "native_avg_duration_ms": average(native_durations),
        "mcp_avg_duration_ms": average(mcp_durations),
        "agent_generated_graphql_avg_duration_ms": average(
            agent_generated_durations
        ),
        "agent_generated_graphql_avg_generation_duration_ms": average(
            agent_generated_generation_durations
        ),
        "interpretation": (
            "GraphQL and MCP should return the same core MiSArch product data. "
            "MCP adds agent-facing metadata and protocol-level tool discovery. "
            "Agent-generated GraphQL is optional and measures whether the model can "
            "produce valid native GraphQL from schema documentation. "
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
            "skip_agent_reports": args.skip_agent_reports,
            "use_llm_controller": args.use_llm_controller,
            "include_agent_generated_graphql": args.include_agent_generated_graphql,
            "agent_generated_graphql_doc_level": (
                args.agent_generated_graphql_doc_level
            ),
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
                "native_llm_controller_used",
                "agent_generated_enabled",
                "agent_generated_success",
                "agent_generated_llm_controller_used",
                "agent_generated_same_core_product_data",
                "agent_generated_failure_stage",
                "agent_generated_doc_level",
                "mcp_success",
                "mcp_llm_controller_used",
                "same_core_product_data",
                "same_product_id",
                "same_name",
                "same_price",
                "native_duration_ms",
                "agent_generated_duration_ms",
                "agent_generated_generation_duration_ms",
                "mcp_duration_ms",
                "mcp_minus_native_duration_ms",
                "native_product_name",
                "agent_generated_product_name",
                "mcp_product_name",
                "mcp_tools",
                "agent_generated_error",
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
            agent_generated = trial.get("agent_generated_graphql", {})
            mcp = trial.get("mcp_gateway", {})
            comparison = trial.get("comparison", {})
            agent_generated_comparison = trial.get(
                "agent_generated_comparison",
                {},
            )
            pending_order = trial.get("pending_order", {})
            native_pending = pending_order.get("native_graphql", {})
            mcp_pending = pending_order.get("mcp_gateway", {})
            pending_comparison = pending_order.get("comparison", {})
            native_product = product_from_native(native) or {}
            agent_generated_product = (
                product_from_agent_generated(agent_generated) or {}
            )
            mcp_product = product_from_mcp(mcp) or {}
            writer.writerow(
                {
                        "trial": trial.get("trial"),
                        "native_success": native.get("success"),
                        "native_llm_controller_used": native.get(
                            "llm_controller_used"
                        ),
                        "agent_generated_enabled": agent_generated.get("enabled"),
                        "agent_generated_success": agent_generated.get("success"),
                        "agent_generated_llm_controller_used": (
                            agent_generated.get("llm_controller_used")
                        ),
                        "agent_generated_same_core_product_data": (
                            agent_generated_comparison.get("same_core_product_data")
                        ),
                        "agent_generated_failure_stage": (
                            agent_generated.get("failure_stage")
                        ),
                        "agent_generated_doc_level": agent_generated.get("doc_level"),
                        "mcp_success": mcp.get("success"),
                        "mcp_llm_controller_used": mcp.get("llm_controller_used"),
                        "same_core_product_data": comparison.get(
                        "same_core_product_data"
                    ),
                    "same_product_id": comparison.get("same_product_id"),
                    "same_name": comparison.get("same_name"),
                    "same_price": comparison.get("same_price"),
                    "native_duration_ms": native.get("duration_ms"),
                    "agent_generated_duration_ms": agent_generated.get("duration_ms"),
                    "agent_generated_generation_duration_ms": (
                        agent_generated.get("generation_duration_ms")
                    ),
                    "mcp_duration_ms": mcp.get("duration_ms"),
                    "mcp_minus_native_duration_ms": comparison.get(
                        "mcp_minus_native_duration_ms"
                    ),
                    "native_product_name": native_product.get("name"),
                    "agent_generated_product_name": agent_generated_product.get("name"),
                    "mcp_product_name": mcp_product.get("name"),
                    "mcp_tools": ",".join(mcp.get("tool_names", [])),
                    "agent_generated_error": agent_generated.get("error"),
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
    needs_model = args.use_llm_controller or args.include_agent_generated_graphql or not (
        args.skip_llm or args.skip_agent_reports
    )
    api_key = load_api_key() if needs_model else None
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
    parser.add_argument(
        "--include-agent-generated-graphql",
        action="store_true",
        help=(
            "Also run Baseline B: ask the model to generate native GraphQL "
            "queries from schema documentation, then execute those queries."
        ),
    )
    parser.add_argument(
        "--use-llm-controller",
        action="store_true",
        help=(
            "Use the same LLM controller for Baseline A and MCP. Baseline A's "
            "controller must choose the fixed GraphQL executor; MCP's controller "
            "must plan tools/list-driven tool calls. Baseline B already uses the "
            "LLM to generate GraphQL."
        ),
    )
    parser.add_argument(
        "--agent-generated-graphql-doc-level",
        choices=("schema", "minimal"),
        default="schema",
        help=(
            "How much GraphQL documentation Baseline B receives. 'schema' gives "
            "a concise schema excerpt; 'minimal' gives no field documentation so "
            "query failures become valid evidence of raw GraphQL difficulty."
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
        help=(
            "Run deterministic GraphQL and MCP calls only; skip all model calls. "
            "This cannot be combined with --include-agent-generated-graphql "
            "or --use-llm-controller."
        ),
    )
    parser.add_argument(
        "--skip-agent-reports",
        action="store_true",
        help=(
            "Skip optional model-generated written reports while still allowing "
            "--include-agent-generated-graphql to use the model for query generation."
        ),
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
    if args.skip_llm and (args.include_agent_generated_graphql or args.use_llm_controller):
        print(
            "ERROR: --include-agent-generated-graphql/--use-llm-controller require model access; "
            "use --skip-agent-reports if you only want to skip written reports",
            file=sys.stderr,
        )
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
