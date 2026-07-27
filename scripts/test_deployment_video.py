from __future__ import annotations

import json
import os
import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_INFRA_DIR = pathlib.Path(
    "/Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker"
)
INFRA_DIR = pathlib.Path(os.environ.get("MISARCH_INFRA_DIR", DEFAULT_INFRA_DIR))
INFRA_OVERRIDE = ROOT / "deploy/video/compose.infrastructure.override.yaml"
GATEWAY_COMPOSE = ROOT / "deploy/video/compose.gateway.yaml"
PREPARE_SCRIPT = ROOT / "scripts/prepare_deployment.sh"
RECORD_SCRIPT = ROOT / "scripts/run_deployment.sh"
OLD_PREPARE_SCRIPT = ROOT / ("scripts/prepare_deployment_" + "video.sh")
OLD_RECORD_SCRIPT = ROOT / ("scripts/run_deployment_" + "video.sh")


def command_app_port(command: list[str]) -> str:
    index = command.index("--app-port")
    return command[index + 1]


class DeploymentVideoContractTest(unittest.TestCase):
    def test_infrastructure_override_has_real_dapr_ports(self) -> None:
        if not (INFRA_DIR / "docker-compose.yaml").is_file():
            self.skipTest(f"MiSArch infrastructure checkout not found: {INFRA_DIR}")
        output = subprocess.check_output(
            [
                "docker",
                "compose",
                "-f",
                str(INFRA_DIR / "docker-compose.yaml"),
                "-f",
                str(INFRA_OVERRIDE),
                "config",
                "--format",
                "json",
            ],
            cwd=INFRA_DIR,
            text=True,
        )
        services = json.loads(output)["services"]
        app_8080 = (
            "gateway",
            "catalog",
            "user",
            "tax",
            "address",
            "shipment",
            "shoppingcart",
            "order",
            "inventory",
            "discount",
            "payment",
            "invoice",
            "notification",
            "simulation",
        )
        for service in app_8080:
            command = services[f"{service}-dapr"]["command"]
            self.assertEqual(command_app_port(command), "8080", service)
            self.assertNotIn("5000", command, service)
        self.assertEqual(
            command_app_port(services["keycloak-dapr"]["command"]),
            "80",
        )
        for service in ("shoppingcart", "order", "invoice"):
            command = services[f"{service}-dapr"]["command"]
            protocol_index = command.index("--app-protocol")
            self.assertEqual(command[protocol_index + 1], "http")

    def test_gateway_compose_targets_host_misarch(self) -> None:
        output = subprocess.check_output(
            [
                "docker",
                "compose",
                "-f",
                str(GATEWAY_COMPOSE),
                "config",
                "--format",
                "json",
            ],
            cwd=ROOT,
            text=True,
        )
        service = json.loads(output)["services"]["agent-gateway"]
        environment = service["environment"]
        self.assertEqual(
            environment["MISARCH_GRAPHQL_URL"],
            "http://host.docker.internal:8080/graphql",
        )
        self.assertEqual(environment["HTTP_ADDR"], ":8001")
        self.assertIn(
            {
                "mode": "ingress",
                "host_ip": "127.0.0.1",
                "target": 8001,
                "published": "8001",
                "protocol": "tcp",
            },
            service["ports"],
        )

    def test_dockerfile_uses_buildkit_caches(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("# syntax=docker/dockerfile:1.7", dockerfile)
        self.assertIn("--mount=type=cache,target=/go/pkg/mod", dockerfile)
        self.assertIn("GOCACHE=/tmp/go-build-cache", dockerfile)
        self.assertNotIn("--mount=type=cache,target=/root/.cache/go-build", dockerfile)

    def test_video_scripts_cover_build_deploy_and_protocol_checks(self) -> None:
        self.assertTrue(PREPARE_SCRIPT.is_file(), PREPARE_SCRIPT)
        self.assertTrue(RECORD_SCRIPT.is_file(), RECORD_SCRIPT)
        self.assertTrue(os.access(PREPARE_SCRIPT, os.X_OK), PREPARE_SCRIPT)
        self.assertTrue(os.access(RECORD_SCRIPT, os.X_OK), RECORD_SCRIPT)
        self.assertFalse(OLD_PREPARE_SCRIPT.exists(), OLD_PREPARE_SCRIPT)
        self.assertFalse(OLD_RECORD_SCRIPT.exists(), OLD_RECORD_SCRIPT)
        recording = RECORD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("go test ./...", recording)
        self.assertIn("build --no-cache", recording)
        self.assertIn("up -d --force-recreate", recording)
        self.assertIn("scripts.mcp_validation_regression", recording)
        self.assertIn("scripts.a2a_negative_e2e", recording)
        self.assertIn("--purchase", recording)

    def test_video_scripts_pass_shell_syntax_check(self) -> None:
        self.assertTrue(PREPARE_SCRIPT.is_file(), PREPARE_SCRIPT)
        self.assertTrue(RECORD_SCRIPT.is_file(), RECORD_SCRIPT)
        subprocess.run(
            ["bash", "-n", str(PREPARE_SCRIPT), str(RECORD_SCRIPT)],
            cwd=ROOT,
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
