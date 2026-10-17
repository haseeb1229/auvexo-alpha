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


def test_invalid_config_does_not_load_http_or_database_stacks() -> None:
    """Refusal must precede server/DB loading, including on a cold Windows interpreter."""
    script = """
import importlib.abc, runpy, sys
class RejectTransport(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('uvicorn', 'sqlalchemy', 'fastapi'):
            raise RuntimeError('transport loaded before configuration refusal')
sys.meta_path.insert(0, RejectTransport())
sys.argv = ['auvexo', 'serve']
runpy.run_module('auvexo_alpha.cli', run_name='__main__')
"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("AUVEXO_")}
    env["AUVEXO_BIND_HOST"] = "0.0.0.0"
    result = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 2 and json.loads(result.stdout)["code"] == "INVALID_CONFIG"
    assert not result.stderr
