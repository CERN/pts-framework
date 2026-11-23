"""pyhal is a package of its own: it must never import pypts."""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pyhal_never_imports_pypts() -> None:
    # Every import statement in src/pyhal, read with ast (no import executed).
    offenders = []
    for path in sorted((REPO_ROOT / "src" / "pyhal").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for name in names:
                if name == "pypts" or name.startswith("pypts."):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {name}")
    assert offenders == []


def test_pyhal_exists() -> None:
    assert (REPO_ROOT / "src" / "pyhal" / "__init__.py").is_file()
