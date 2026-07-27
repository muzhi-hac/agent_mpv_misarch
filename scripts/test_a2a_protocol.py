#!/usr/bin/env python3
"""Wire-level tests for the Arm C A2A 1.0 JSON-RPC client."""
from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from scripts.agent_a2a_loop import A2AClient


class _A2AFixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: Any) -> None:
        pass

    def do_GET(self) -> None:
        if self.path != "/.well-known/agent-card.json":
            self.send_error(404)
            return
        card = {
            "name": "fixture-store-agent",
            "description": "test",
            "version": "1.0.0",
            "supportedInterfaces": [{
                "url": self.server.a2a_url,  # type: ignore[attr-defined]
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }],
            "capabilities": {},
            "defaultInputModes": ["application/json"],
            "defaultOutputModes": ["application/json"],
            "skills": [],
        }
        self._write_json(card)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.captured = {  # type: ignore[attr-defined]
            "path": self.path,
            "headers": dict(self.headers.items()),
            "json": request,
        }
        skill = request["params"]["message"]["parts"][0]["data"]["skill"]
        artifact = {
            "products": [{"product_id": "p1", "name": "Steel Cup"}],
            "returned_count": 1,
        } if skill == "browse" else {}
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "task": {
                    "id": "server-task-1",
                    "contextId": "context-1",
                    "status": {"state": "TASK_STATE_COMPLETED"},
                    "artifacts": [{
                        "artifactId": "artifact-1",
                        "parts": [{"data": artifact}],
                    }],
                }
            },
        }
        self._write_json(response)

    def _write_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class A2AProtocolClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _A2AFixtureHandler)
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"
        self.server.a2a_url = self.base_url + "/a2a"  # type: ignore[attr-defined]
        self.server.captured = None  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_discovers_interface_and_sends_standard_message(self) -> None:
        client = A2AClient(self.base_url)
        card = client.fetch_card()
        self.assertEqual(card["supportedInterfaces"][0]["protocolBinding"], "JSONRPC")

        result = client.send_task("browse-run", "browse", {"query": "cup", "top_k": 5})

        captured = self.server.captured  # type: ignore[attr-defined]
        self.assertEqual(captured["path"], "/a2a")
        self.assertEqual(captured["headers"]["A2A-Version"], "1.0")
        self.assertEqual(captured["headers"]["User-Agent"], "misarch-a2a-e2e/1.0")
        request = captured["json"]
        self.assertEqual(request["jsonrpc"], "2.0")
        self.assertEqual(request["method"], "SendMessage")
        self.assertEqual(request["params"]["message"]["role"], "ROLE_USER")
        self.assertEqual(
            request["params"]["message"]["parts"][0]["data"]["skill"],
            "browse",
        )
        self.assertEqual(result["task_id"], "server-task-1")
        self.assertEqual(result["context_id"], "context-1")
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["artifact"]["products"][0]["product_id"], "p1")

    def test_continuation_references_task_and_context(self) -> None:
        client = A2AClient(self.base_url)
        result = client.continue_task(
            "confirmed",
            "existing-task",
            "existing-context",
            "purchase",
            {"confirmed": True},
        )

        captured = self.server.captured  # type: ignore[attr-defined]
        message = captured["json"]["params"]["message"]
        self.assertEqual(message["taskId"], "existing-task")
        self.assertEqual(message["contextId"], "existing-context")
        self.assertTrue(message["parts"][0]["data"]["input"]["confirmed"])
        self.assertEqual(result["context_id"], "context-1")

    def test_sends_optional_bearer_token(self) -> None:
        client = A2AClient(self.base_url, bearer_token="test-gateway-token")
        client.fetch_card()
        client.send_task("secured-browse", "browse", {"query": "cup"})

        captured = self.server.captured  # type: ignore[attr-defined]
        self.assertEqual(
            captured["headers"]["Authorization"],
            "Bearer test-gateway-token",
        )

    def test_rejects_jsonrpc_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "A2A JSON-RPC error -32602"):
            A2AClient._adapt_send_result({
                "jsonrpc": "2.0",
                "id": "bad",
                "error": {"code": -32602, "message": "invalid params"},
            })

    def test_rejects_direct_message_result(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "direct Message"):
            A2AClient._adapt_send_result({
                "jsonrpc": "2.0",
                "id": "message",
                "result": {
                    "message": {
                        "messageId": "m1",
                        "role": "ROLE_AGENT",
                        "parts": [{"text": "done"}],
                    }
                },
            })

    def test_rejects_unsupported_card_transport(self) -> None:
        client = A2AClient("http://unused.test")
        client.card = {
            "supportedInterfaces": [{
                "url": "http://unused.test/grpc",
                "protocolBinding": "GRPC",
                "protocolVersion": "1.0",
            }]
        }
        with self.assertRaisesRegex(RuntimeError, "does not advertise.*JSONRPC"):
            client.send_task("browse", "browse", {})


if __name__ == "__main__":
    unittest.main()
