#!/usr/bin/env python3
"""Create a tiny, idempotent local catalog for the four-arm video demo."""
from __future__ import annotations

import json
import os
import sys
from typing import Any

os.environ.setdefault("KEYCLOAK_URL", "http://127.0.0.1:8081/keycloak")
os.environ.setdefault("GRAPHQL_ENDPOINT", "http://127.0.0.1:8080/graphql")

from scripts import seed_realistic_catalog as seed


DEMO_CATEGORY = {
    "name": "Video Demo Cups",
    "description": "Small local-only catalog used for the four-arm terminal recording.",
}

DEMO_PRODUCTS: list[tuple[str, str, str, int, float, int]] = [
    (
        "Budget Plastic Cup",
        "Lightweight reusable cup for the lowest-price policy.",
        "Plastic",
        799,
        0.12,
        5,
    ),
    (
        "Borosilicate Glass Cup",
        "Heat-resistant glass cup for hot and cold drinks.",
        "Glass",
        1299,
        0.25,
        5,
    ),
    (
        "Stainless Steel Cup 500ml",
        "Insulated 500 ml cup matching the demo user's material preference.",
        "Stainless Steel",
        2499,
        0.32,
        5,
    ),
    (
        "Titanium Trail Cup",
        "Ultralight premium camping cup.",
        "Titanium",
        7999,
        0.09,
        5,
    ),
]


def existing_products(token: str) -> dict[str, dict[str, Any]]:
    data = seed.graphql(
        """
        query VideoDemoProducts {
          products(first: 100) {
            nodes {
              id
              defaultVariant {
                id
                currentVersion { name retailPrice }
              }
            }
          }
        }
        """,
        {},
        token,
    )
    found: dict[str, dict[str, Any]] = {}
    for product in data["products"]["nodes"]:
        version = (product.get("defaultVariant") or {}).get("currentVersion") or {}
        name = str(version.get("name") or "")
        if name:
            found[name] = product
    return found


def existing_demo_category(token: str) -> dict[str, Any] | None:
    data = seed.graphql(
        """
        query VideoDemoCategories {
          categories(first: 100) {
            nodes {
              id
              name
              description
              characteristics(first: 10) {
                nodes { id name }
              }
            }
          }
        }
        """,
        {},
        token,
    )
    for category in data["categories"]["nodes"]:
        if category.get("name") != DEMO_CATEGORY["name"]:
            continue
        characteristics = (category.get("characteristics") or {}).get("nodes") or []
        if not characteristics:
            raise RuntimeError("existing video demo category has no characteristic")
        return {
            "id": category["id"],
            "name": category["name"],
            "description": category.get("description"),
            "characteristic_id": characteristics[0]["id"],
            "characteristic_name": characteristics[0]["name"],
        }
    return None


def discover_tax_rate_id(token: str) -> str:
    data = seed.graphql(
        """
        query VideoDemoTaxRate {
          taxRates(first: 10) {
            nodes { id }
          }
        }
        """,
        {},
        token,
    )
    nodes = data["taxRates"]["nodes"]
    if not nodes:
        raise RuntimeError("no tax rate is available for demo products")
    return str(nodes[0]["id"])


def run() -> dict[str, Any]:
    token = seed.get_access_token()
    existing = existing_products(token)
    wanted_names = [item[0] for item in DEMO_PRODUCTS]
    missing = [item for item in DEMO_PRODUCTS if item[0] not in existing]
    if not missing:
        return {
            "success": True,
            "created": [],
            "already_available": wanted_names,
        }

    category = existing_demo_category(token)
    if category is None:
        category = seed.create_category(token, DEMO_CATEGORY)

    seed.SEED_ID = "VIDEO-DEMO-20260727"
    seed.TAX_RATE_ID = discover_tax_rate_id(token)
    created = [
        seed.create_product(token, category, product, index)
        for index, product in enumerate(missing, start=1)
    ]
    return {
        "success": True,
        "created": [
            {
                "product_id": item["product_id"],
                "variant_id": item["variant_id"],
                "name": item["name"],
                "retail_price_cents": item["retail_price_cents"],
                "inventory_count": item["inventory_count_after_restock"],
            }
            for item in created
        ],
        "already_available": [
            name for name in wanted_names if name in existing
        ],
    }


def main() -> int:
    try:
        print(json.dumps(run(), ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(
            json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
