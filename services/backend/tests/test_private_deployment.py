"""Compose's resolved configuration keeps secrets and services behind loopback TLS."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_resolved_compose_has_one_loopback_port_and_explicit_migration():
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose is required for deployment configuration validation")
    env = os.environ.copy()
    env["ALPHASENSE_BUILD_GIT_SHA"] = "a" * 40
    env["ALPHASENSE_PRIVATE_SECRETS_DIR"] = str(ROOT / ".local-postgres" / "config-test")
    try:
        result = subprocess.run(
            [
                docker,
                "compose",
                "-f",
                "compose.private.yaml",
                "--profile",
                "ops",
                "config",
                "--format",
                "json",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            check=True,
            timeout=20,
        )
        config = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        pytest.fail("Private Compose configuration validation failed", pytrace=False)
    services = config["services"]
    assert set(services) == {
        "db",
        "api",
        "sec-worker",
        "document-worker",
        "scheduler",
        "migrate",
        "proxy",
    }
    assert config["name"] == "alphasense-private"
    for name, service in services.items():
        if name != "proxy":
            assert not service.get("ports"), "A private service publishes a host port"
        assert service["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in service["security_opt"]
        assert service["restart"] == ("no" if name == "migrate" else "unless-stopped")
        assert "POSTGRES_PASSWORD" not in service.get("environment", {})
        assert "ALPHASENSE_DATABASE_URL" not in service.get("environment", {})
        assert "GEMINI_API_KEY" not in service.get("environment", {})
        assert not any("owner-token" in item["source"] for item in service.get("secrets", []))
    port = services["proxy"]["ports"]
    assert len(port) == 1 and port[0]["host_ip"] == "127.0.0.1"
    assert str(port[0]["published"]) == "8443" and port[0]["target"] == 8443
    assert services["api"]["environment"]["ALPHASENSE_PRIVATE_ORIGIN"] == "https://localhost:8443"
    # Compose unescapes YAML strings; validate the actual command after resolution.
    healthcheck = services["api"]["healthcheck"]["test"]
    assert healthcheck[:3] == ["CMD", "python", "-c"]
    compile(healthcheck[3], "private-api-healthcheck", "exec")
    for name in ("api", "sec-worker", "document-worker", "scheduler", "migrate"):
        assert services[name]["user"] == "10001:10001" and services[name]["read_only"] is True
        assert services[name]["init"] is True
    assert services["migrate"]["profiles"] == ["ops"]
    assert config["networks"]["database"]["internal"] is True
    assert set(services["scheduler"]["networks"]) == {"database"}
    assert set(services["document-worker"]["networks"]) == {"database"}


def test_dockerfile_and_proxy_do_not_copy_workspace_secrets_or_disable_tls():
    dockerfile = (ROOT / "deploy/private/Dockerfile").read_text("utf-8")
    copied = [line for line in dockerfile.splitlines() if line.startswith("COPY ")]
    assert not any(" . ." in line or ".local-postgres" in line or ".env" in line for line in copied)
    assert "USER 10001:10001" in dockerfile
    assert "ARG BUILD_GIT_SHA" in dockerfile
    caddy = (ROOT / "deploy/private/Caddyfile").read_text("utf-8")
    assert "https://localhost:8443" in caddy and "tls internal" in caddy
    assert "admin off" in caddy and "tls_insecure_skip_verify" not in caddy
