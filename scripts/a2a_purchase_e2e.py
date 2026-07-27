#!/usr/bin/env python3
"""Guarded end-to-end runner for one complete local MiSArch purchase.

This runner creates real MiSArch test data and drives the local payment
Simulation service. It never contacts an external payment provider, but it can
reserve inventory and create downstream order/payment/invoice records.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import uuid
from typing import Any

from scripts.agent_a2a_loop import A2AClient


CONFIRMATION_TEXT = "CREATE AND PAY ONE LOCAL TEST ORDER"


def valid_uuid(value: str) -> str:
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid UUID: {value!r}") from exc
    return value


def quantity(value: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > 3:
        raise argparse.ArgumentTypeError("quantity must be between 1 and 3")
    return parsed


def payment_cvc(value: str) -> int:
    if not value.isdigit() or len(value) not in (3, 4):
        raise argparse.ArgumentTypeError("payment CVC must contain 3 or 4 digits")
    return int(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create, place, and locally simulate payment for one MiSArch test order."
    )
    parser.add_argument("--a2a-url", required=True)
    parser.add_argument("--user-id", required=True, type=valid_uuid)
    parser.add_argument("--product-variant-id", required=True, type=valid_uuid)
    parser.add_argument("--shipment-method-id", required=True, type=valid_uuid)
    parser.add_argument("--shipment-address-id", required=True, type=valid_uuid)
    parser.add_argument("--invoice-address-id", required=True, type=valid_uuid)
    parser.add_argument("--payment-information-id", required=True, type=valid_uuid)
    parser.add_argument("--quantity", default=1, type=quantity)
    parser.add_argument("--coupon-id", action="append", default=[], type=valid_uuid)
    parser.add_argument("--payment-cvc", type=payment_cvc)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirmation-text", default="")
    parser.add_argument("--output", required=True)
    return parser


def purchase_input(args: argparse.Namespace, confirmed: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user_id": args.user_id,
        "product_variant_id": args.product_variant_id,
        "quantity": args.quantity,
        "shipment_method_id": args.shipment_method_id,
        "shipment_address_id": args.shipment_address_id,
        "invoice_address_id": args.invoice_address_id,
        "payment_information_id": args.payment_information_id,
        "coupon_ids": list(args.coupon_id),
        "confirmed": confirmed,
    }
    if confirmed and args.payment_cvc is not None:
        payload["payment_cvc"] = args.payment_cvc
    return payload


def run_purchase(
    args: argparse.Namespace,
    client: A2AClient | None = None,
) -> dict[str, Any]:
    if not args.execute:
        raise RuntimeError("refusing mutation: --execute is required")
    if args.confirmation_text != CONFIRMATION_TEXT:
        raise RuntimeError(
            f"refusing mutation: --confirmation-text must equal {CONFIRMATION_TEXT!r}"
        )

    a2a = client or A2AClient(args.a2a_url)
    first = a2a.send_task("purchase-preview", "purchase", purchase_input(args, False))
    if first.get("state") != "input-required":
        raise RuntimeError(
            f"purchase preview returned {first.get('state')!r}, want 'input-required'"
        )
    first_artifact = first.get("artifact") or {}
    if first_artifact.get("order_created") is not False:
        raise RuntimeError("purchase preview unexpectedly created an order")

    task_id = str(first.get("task_id") or "")
    context_id = str(first.get("context_id") or "")
    if not task_id or not context_id:
        raise RuntimeError("purchase preview did not return task_id and context_id")

    confirmed = a2a.continue_task(
        "purchase-confirmed",
        task_id,
        context_id,
        "purchase",
        purchase_input(args, True),
    )
    if confirmed.get("state") != "completed":
        raise RuntimeError(
            f"confirmed purchase returned {confirmed.get('state')!r}: "
            f"{confirmed.get('error') or confirmed.get('message') or 'unknown error'}"
        )

    artifact = confirmed.get("artifact") or {}
    purchase = artifact.get("purchase") or {}
    required = {
        "order_status": "PLACED",
        "payment_status": "SUCCEEDED",
    }
    for field, expected in required.items():
        if purchase.get(field) != expected:
            raise RuntimeError(
                f"confirmed purchase {field}={purchase.get(field)!r}, want {expected!r}"
            )
    for field in ("order_id", "shopping_cart_item_id", "payment_id"):
        if not purchase.get(field):
            raise RuntimeError(f"confirmed purchase is missing {field}")

    audit = {
        "success": True,
        "local_simulation_only": True,
        "task_id": str(confirmed.get("task_id") or task_id),
        "context_id": str(confirmed.get("context_id") or context_id),
        "request": {
            key: value
            for key, value in purchase_input(args, True).items()
            if key != "payment_cvc"
        },
        "purchase": purchase,
    }
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = run_purchase(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    purchase = result["purchase"]
    print(
        "PASS local purchase: "
        f"order={purchase['order_id']} {purchase['order_status']}, "
        f"payment={purchase['payment_id']} {purchase['payment_status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
