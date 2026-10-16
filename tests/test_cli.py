import json
import os
import secrets
import subprocess
import sys

import pytest


@pytest.mark.parametrize("command", ["doctor", "health", "validate-config", "serve"])
def test_cli_invalid_config_is_redacted(command: str) -> None:
    secret = secrets.token_urlsafe(32)
    env = {k: v for k, v in os.environ.items() if not k.startswith("AUVEXO_")}
    env.update(AUVEXO_DB_PASSWORD=secret, AUVEXO_API_TOKEN=secret, AUVEXO_BIND_HOST="0.0.0.0")
    result = subprocess.run(
        [sys.executable, "-m", "auvexo_alpha.cli", command],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["code"] == "INVALID_CONFIG"
    assert secret not in result.stdout + result.stderr
    assert not result.stderr
