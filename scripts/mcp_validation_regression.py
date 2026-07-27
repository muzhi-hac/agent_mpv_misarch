#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

from scripts.agent_mcp_loop import MCPClient


DANGEROUS_TOOLS = {
    "execute_graphql",
    "process_payment",
    "create_refund",
    "dispatch_shipment",
    "update_inventory_admin",
    "keycloak_admin",
    "execute_sql",
    "publish_event",
}

VALID_UUID_FIELDS = {
    "user_id": "00000000-0000-4000-8000-000000000001",
    "product_variant_id": "00000000-0000-4000-8000-000000000002",
    "shipment_method_id": "00000000-0000-4000-8000-000000000003",
    "shipment_address_id": "00000000-0000-4000-8000-000000000004",
    "invoice_address_id": "00000000-0000-4000-8000-000000000005",
    "payment_information_id": "00000000-0000-4000-8000-000000000006",
}


def validation_cases() -> list[dict[str, Any]]:
    return [
        {
            "name": "invalid_product_uuid",
            "tool": "get_product",
            "arguments": {"product_id": "not-a-uuid"},
        },
        {
            "name": "missing_order_fields",
            "tool": "create_pending_order",
            "arguments": {},
        },
        {
            "name": "zero_quantity",
            "tool": "create_pending_order",
            "arguments": {**VALID_UUID_FIELDS, "quantity": 0},
        },
        {
            "name": "excessive_quantity",
            "tool": "create_pending_order",
            "arguments": {**VALID_UUID_FIELDS, "quantity": 4},
        },
        {
            "name": "generic_graphql_not_exposed",
            "tool": "execute_graphql",
            "arguments": {"query": "{ __typename }"},
        },
    ]


def run_case(client: MCPClient, case: dict[str, Any]) -> dict[str, Any]:
    try:
        result = client.call_tool(case["tool"], case["arguments"])
    except Exception as exc:
        return {
            "name": case["name"],
            "tool": case["tool"],
            "rejected": True,
            "error": " ".join(str(exc).split()),
        }
    return {
        "name": case["name"],
        "tool": case["tool"],
        "rejected": False,
        "unexpected_result": result,
    }


def run(mcp_url: str) -> dict[str, Any]:
    client = MCPClient(mcp_url)
    client.connect()
    tools = client.list_tools()
    tool_names = sorted(
        tool["name"] for tool in tools if isinstance(tool.get("name"), str)
    )
    cases = [run_case(client, case) for case in validation_cases()]
    dangerous_exposed = sorted(DANGEROUS_TOOLS.intersection(tool_names))
    return {
        "success": not dangerous_exposed and all(case["rejected"] for case in cases),
        "mcp_url": mcp_url,
        "server_info": client.server_info,
        "tool_count": len(tool_names),
        "tool_names": tool_names,
        "tools": tools,
        "dangerous_tools_exposed": dangerous_exposed,
        "negative_cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live MCP boundary regressions.")
    parser.add_argument("--mcp-url", default="http://127.0.0.1:8001/mcp")
    parser.add_argument("--output", default="eval/mcp-validation.json")
    args = parser.parse_args()

    result = run(args.mcp_url)
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
