"""Transient test state must not obstruct managed quota traversal."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from auvexo_alpha.infrastructure.data_store import tree_bytes


@pytest.mark.parametrize("success", [True, False])
def test_pytest_cache_is_external_unique_and_removed_even_on_failure(
    tmp_path: Path, success: bool
) -> None:
    root = Path(__file__).resolve().parents[1]
    observed = tmp_path / "observed.json"
    child = tmp_path / "test_synthetic_cache.py"
    child.write_text(
        "import json\nfrom pathlib import Path\n"
        "def test_cache(request):\n"
        "    cache = request.config.cache._cachedir\n"
        "    request.config.cache.set('synthetic/marker', 'test-only')\n"
        f"    Path({str(observed)!r}).write_text(json.dumps(str(cache)))\n"
        f"    assert {success!r}\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(root / "tools/run_tests.py"),
            "-q",
            str(child),
            # A stale caller override must not put cache back in managed storage.
            "-o",
            f"cache_dir={tmp_path / 'managed' / 'forbidden-cache'}",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == (0 if success else 1), result.stdout + result.stderr
    cache = Path(json.loads(observed.read_text()))
    assert cache.parent.name.startswith("auvexo-pytest-")
    assert not cache.is_relative_to(root / ".local")
    assert not cache.parent.exists()
    assert not (tmp_path / "managed/forbidden-cache").exists()


def test_quota_counts_synthetic_cache_bytes_and_refuses_unreadable_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    managed = tmp_path / "managed"
    cache = managed / "pytest-cache"
    cache.mkdir(parents=True)
    (cache / "synthetic").write_bytes(b"123456789")
    assert tree_bytes(managed, True) == 9
    from auvexo_alpha.infrastructure import data_store

    real_scandir = data_store.os.scandir

    def denied_scandir(path: str | Path):
        if Path(path) == cache:
            raise PermissionError("synthetic unreadable managed path")
        return real_scandir(path)

    monkeypatch.setattr(data_store.os, "scandir", denied_scandir)
    with pytest.raises(PermissionError, match="synthetic unreadable managed path"):
        tree_bytes(managed, True)
