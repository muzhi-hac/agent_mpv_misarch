#!/usr/bin/env python3
"""Read a seeded MiSArch user's IDs for the guarded purchase E2E runner."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import uuid
from typing import Any

from scripts.agent_gcp_baseline_test import (
    GET_ACTIVE_ADDRESSES_QUERY,
    GET_CURRENT_USER_QUERY,
    GET_PAYMENT_INFORMATIONS_QUERY,
    GET_SHIPMENT_METHODS_QUERY,
    LIST_PRODUCTS_QUERY,
    bearer_headers,
    graphql_request,
    keycloak_token,
)


def _nodes(response: dict[str, Any], *path: str) -> list[dict[str, Any]]:
    current: Any = response.get("data", {})
    for key in path:
        if not isinstance(current, dict):
            return []
        current = current.get(key)
    if not isinstance(current, dict) or not isinstance(current.get("nodes"), list):
        return []
    return [node for node in current["nodes"] if isinstance(node, dict)]


def _valid_uuid(value: Any) -> str:
    text = str(value or "")
    uuid.UUID(text)
    return text


def discover(args: argparse.Namespace) -> dict[str, Any]:
    token = keycloak_token(args)
    headers = bearer_headers(token)

    products_response = graphql_request(
        args.graphql_url,
        LIST_PRODUCTS_QUERY,
        {"first": 100},
        headers,
    )
    products = _nodes(products_response, "products")
    usable_products = [
        product
        for product in products
        if isinstance(product.get("defaultVariant"), dict)
        and product["defaultVariant"].get("id")
    ]
    if not usable_products:
        raise RuntimeError("no product with a default variant is available")
    product = next(
        (
            item
            for item in usable_products
            if "cup"
            in str(
                (item.get("defaultVariant") or {}).get("currentVersion", {}).get("name", "")
            ).lower()
        ),
        usable_products[0],
    )

    user_response = graphql_request(
        args.graphql_url,
        GET_CURRENT_USER_QUERY,
        {},
        headers,
    )
    user = (user_response.get("data") or {}).get("currentUser") or {}

    addresses_response = graphql_request(
        args.graphql_url,
        GET_ACTIVE_ADDRESSES_QUERY,
        {},
        headers,
    )
    addresses = _nodes(addresses_response, "currentUser", "addresses")
    if not addresses:
        raise RuntimeError("the seeded user has no active address")

    payments_response = graphql_request(
        args.graphql_url,
        GET_PAYMENT_INFORMATIONS_QUERY,
        {},
        headers,
    )
    payments = _nodes(payments_response, "currentUser", "paymentInformations")
    if not payments:
        raise RuntimeError("the seeded user has no payment information")
    # The current MiSArch PREPAYMENT processor emits the "payment enabled"
    # event but does not persist SUCCEEDED. Prefer INVOICE so the local
    # Simulation callback produces the paid state that this E2E verifies.
    payment = next(
        (item for item in payments if item.get("paymentMethod") == "INVOICE"),
        payments[0],
    )

    shipment_response = graphql_request(
        args.graphql_url,
        GET_SHIPMENT_METHODS_QUERY,
        {},
        headers,
    )
    shipment_methods = _nodes(shipment_response, "shipmentMethods")
    if not shipment_methods:
        raise RuntimeError("no active shipment method is available")

    variant = product["defaultVariant"]
    current_version = variant.get("currentVersion") or {}
    fixture = {
        "user_id": _valid_uuid(user.get("id")),
        "product_variant_id": _valid_uuid(variant.get("id")),
        "quantity": 1,
        "shipment_method_id": _valid_uuid(shipment_methods[0].get("id")),
        "shipment_address_id": _valid_uuid(addresses[0].get("id")),
        "invoice_address_id": _valid_uuid(addresses[0].get("id")),
        "payment_information_id": _valid_uuid(payment.get("id")),
        "coupon_ids": [],
    }
    return {
        "fixture": fixture,
        "selection": {
            "product_id": _valid_uuid(product.get("id")),
            "product_name": current_version.get("name"),
            "payment_method": payment.get("paymentMethod"),
            "shipment_method_name": shipment_methods[0].get("name"),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover read-only MiSArch purchase IDs.")
    parser.add_argument(
        "--graphql-url",
        default=os.environ.get("MISARCH_GRAPHQL_URL", "http://127.0.0.1:8080/graphql"),
    )
    parser.add_argument(
        "--keycloak-token-url",
        default=os.environ.get(
            "MISARCH_KEYCLOAK_TOKEN_URL",
            "http://127.0.0.1:8081/keycloak/realms/Misarch/protocol/openid-connect/token",
        ),
    )
    parser.add_argument(
        "--keycloak-client-id",
        default=os.environ.get("MISARCH_KEYCLOAK_CLIENT_ID", "frontend"),
    )
    parser.add_argument(
        "--keycloak-username",
        default=os.environ.get("MISARCH_KEYCLOAK_USERNAME", "gatling"),
    )
    parser.add_argument(
        "--keycloak-password",
        default=os.environ.get("MISARCH_KEYCLOAK_PASSWORD", "123"),
    )
    parser.add_argument("--keycloak-grant-type", default="password")
    parser.add_argument("--output", default="tmp/report-e2e/purchase-fixture.json")
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        result = discover(args)
        output = pathlib.Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
