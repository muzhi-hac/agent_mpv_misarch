from __future__ import annotations

import argparse
import json
import pathlib
import tempfile
import unittest

from scripts.a2a_purchase_e2e import CONFIRMATION_TEXT, run_purchase


UUIDS = {
    "user_id": "11111111-1111-4111-8111-111111111111",
    "product_variant_id": "22222222-2222-4222-8222-222222222222",
    "shipment_method_id": "33333333-3333-4333-8333-333333333333",
    "shipment_address_id": "44444444-4444-4444-8444-444444444444",
    "invoice_address_id": "55555555-5555-4555-8555-555555555555",
    "payment_information_id": "66666666-6666-4666-8666-666666666666",
}


class FakeA2AClient:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def send_task(self, label, skill, payload):
        self.calls.append(("send", label, skill, payload))
        return {
            "task_id": "task-1",
            "context_id": "context-1",
            "state": "input-required",
            "artifact": {
                "confirmation_required": True,
                "order_created": False,
            },
        }

    def continue_task(self, label, task_id, context_id, skill, payload):
        self.calls.append(
            ("continue", label, task_id, context_id, skill, payload)
        )
        return {
            "task_id": task_id,
            "context_id": context_id,
            "state": "completed",
            "artifact": {
                "order_created": True,
                "order_placed": True,
                "payment_succeeded": True,
                "purchase": {
                    "order_id": "order-1",
                    "order_status": "PLACED",
                    "shopping_cart_item_id": "cart-1",
                    "payment_id": "order-1",
                    "payment_status": "SUCCEEDED",
                },
            },
        }


def args_for(output: str, *, execute: bool = True, confirmation: str = CONFIRMATION_TEXT):
    return argparse.Namespace(
        a2a_url="http://example.test",
        quantity=1,
        coupon_id=[],
        payment_cvc=123,
        execute=execute,
        confirmation_text=confirmation,
        output=output,
        **UUIDS,
    )


class PurchaseE2ETest(unittest.TestCase):
    def test_requires_execute_and_exact_confirmation_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = str(pathlib.Path(tmp) / "audit.json")
            with self.assertRaisesRegex(RuntimeError, "--execute"):
                run_purchase(args_for(output, execute=False), FakeA2AClient())
            with self.assertRaisesRegex(RuntimeError, "--confirmation-text"):
                run_purchase(args_for(output, confirmation="yes"), FakeA2AClient())

    def test_sends_unconfirmed_then_confirmed_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / "audit.json"
            client = FakeA2AClient()
            result = run_purchase(args_for(str(output)), client)

            self.assertTrue(result["success"])
            self.assertEqual(client.calls[0][0:3], ("send", "purchase-preview", "purchase"))
            self.assertFalse(client.calls[0][3]["confirmed"])
            continuation = client.calls[1]
            self.assertEqual(continuation[0], "continue")
            self.assertEqual(continuation[2:4], ("task-1", "context-1"))
            self.assertTrue(continuation[5]["confirmed"])
            self.assertEqual(result["purchase"]["order_status"], "PLACED")
            self.assertEqual(result["purchase"]["payment_status"], "SUCCEEDED")

            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotIn("payment_cvc", written["request"])
            self.assertNotIn("123", output.read_text(encoding="utf-8"))

    def test_rejects_non_succeeded_payment(self) -> None:
        class FailedPayment(FakeA2AClient):
            def continue_task(self, *args):
                result = super().continue_task(*args)
                result["artifact"]["purchase"]["payment_status"] = "FAILED"
                return result

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "payment_status"):
                run_purchase(
                    args_for(str(pathlib.Path(tmp) / "audit.json")),
                    FailedPayment(),
                )


if __name__ == "__main__":
    unittest.main()
