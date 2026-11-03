import ast
import importlib.metadata
import sys
from pathlib import Path


def test_r019_p1_import_direction() -> None:
    root = Path("src/auvexo_alpha")
    for area, forbidden in {
        "domain": (
            "fastapi",
            "sqlalchemy",
            "psycopg",
            "auvexo_alpha.api",
            "auvexo_alpha.infrastructure",
            "auvexo_alpha.application",
        ),
        "application": (
            "fastapi",
            "sqlalchemy",
            "psycopg",
            "auvexo_alpha.api",
            "auvexo_alpha.infrastructure",
        ),
    }.items():
        for file in (root / area).rglob("*.py"):
            for node in ast.walk(ast.parse(file.read_text())):
                modules = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else []
                )
                if isinstance(node, ast.ImportFrom):
                    assert node.level == 0, "Use explicit absolute imports for boundary review"
                assert not any(m.startswith(forbidden) for m in modules), file


def test_r022_p1_no_broker_dependencies() -> None:
    packages = {str(d.metadata["Name"]).lower() for d in importlib.metadata.distributions()}
    # ADR-029 permits only the exact Windows provider; every other broker ban remains.
    assert not packages.intersection({"ccxt", "python-binance", "binance-connector", "pybit"})
    if "metatrader5" in packages:
        assert sys.platform == "win32"
        assert importlib.metadata.version("metatrader5") == "5.0.6231"
    for file in Path("src").rglob("*.py"):
        tree = ast.parse(file.read_text())
        for node in ast.walk(tree):
            modules = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for module in modules:
                assert not module.lower().startswith(("ccxt", "binance", "pybit")), file
                if module.lower().startswith("metatrader5"):
                    assert module == "MetaTrader5"
                    assert file.as_posix() == "src/auvexo_alpha/infrastructure/ds03_mt5.py"


def test_r032_agent_instructions_aligned() -> None:
    assert Path("AGENTS.md").read_bytes() == Path("CLAUDE.md").read_bytes()
