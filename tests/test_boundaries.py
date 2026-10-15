import ast
import importlib.metadata
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
    assert not packages.intersection(
        {"metatrader5", "ccxt", "python-binance", "binance-connector", "pybit"}
    )
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
            assert not any(
                m.lower().startswith(("metatrader5", "ccxt", "binance", "pybit")) for m in modules
            )


def test_r032_agent_instructions_aligned() -> None:
    assert Path("AGENTS.md").read_bytes() == Path("CLAUDE.md").read_bytes()
