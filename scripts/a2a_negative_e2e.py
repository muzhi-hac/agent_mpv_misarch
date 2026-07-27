#!/usr/bin/env python3
"""Live, non-mutating A2A purchase-boundary regression scenarios."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

from scripts.agent_a2a_loop import A2AClient


FIXTURE = {
    "user_id": "11111111-1111-4111-8111-111111111111",
    "product_variant_id": "22222222-2222-4222-8222-222222222222",
    "quantity": 1,
    "shipment_method_id": "33333333-3333-4333-8333-333333333333",
    "shipment_address_id": "44444444-4444-4444-8444-444444444444",
    "invoice_address_id": "55555555-5555-4555-8555-555555555555",
    "payment_information_id": "66666666-6666-4666-8666-666666666666",
    "coupon_ids": [],
}


def run(base_url: str) -> dict[str, Any]:
    client = A2AClient(base_url)
    rows = []

    missing = client.send_task(
        "negative-missing-fields",
        "purchase",
        {"user_id": FIXTURE["user_id"], "confirmed": False},
    )
    rows.append({
        "id": "BUY-F01",
        "passed": (
            missing.get("state") == "input-required"
            and "product_variant_id"
            in ((missing.get("artifact") or {}).get("missing_fields") or [])
        ),
        "state": missing.get("state"),
    })

    first_confirmed = client.send_task(
        "negative-first-confirmed",
        "purchase",
        {**FIXTURE, "confirmed": True},
    )
    first_artifact = first_confirmed.get("artifact") or {}
    rows.append({
        "id": "BUY-F05",
        "passed": (
            first_confirmed.get("state") == "input-required"
            and first_artifact.get("order_created") is False
        ),
        "state": first_confirmed.get("state"),
    })

    preview = client.send_task(
        "negative-preview-tamper",
        "purchase",
        {**FIXTURE, "confirmed": False},
    )
    tampered = client.continue_task(
        "negative-confirm-tamper",
        str(preview.get("task_id") or ""),
        str(preview.get("context_id") or ""),
        "purchase",
        {**FIXTURE, "quantity": 2, "confirmed": True},
    )
    rows.append({
        "id": "BUY-F07",
        "passed": (
            preview.get("state") == "input-required"
            and tampered.get("state") == "failed"
            and "do not match" in str(tampered.get("error") or "")
        ),
        "preview_state": preview.get("state"),
        "confirmation_state": tampered.get("state"),
    })

    return {
        "success": all(row["passed"] for row in rows),
        "mutation_expected": False,
        "results": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run non-mutating A2A negative E2E tests.")
    parser.add_argument("--a2a-url", default="http://127.0.0.1:8001")
    parser.add_argument("--output", default="tmp/report-e2e/a2a-negative-e2e.json")
    args = parser.parse_args()
    try:
        result = run(args.a2a_url)
        output = pathlib.Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["success"] else 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
