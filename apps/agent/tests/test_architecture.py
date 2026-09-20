from __future__ import annotations

import ast
from pathlib import Path

import apps.agent.core as agent_core
import apps.agent.tools as agent_tools


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def python_modules(directory: str) -> list[Path]:
    return [
        path
        for path in (PROJECT_ROOT / "apps" / directory).glob("*.py")
        if path.name not in {"apps.py", "admin.py"}
    ]


def test_agent_core_does_not_import_concrete_providers():
    imports = imported_modules(Path(agent_core.__file__))

    assert "apps.agent.providers.ollama" not in imports
    assert "apps.agent.providers.mistral" not in imports


def test_tools_do_not_depend_on_concrete_providers():
    tool_directory = Path(agent_tools.__file__).parent

    for path in tool_directory.glob("*.py"):
        imports = imported_modules(path)
        assert "apps.agent.providers.ollama" not in imports
        assert "apps.agent.providers.mistral" not in imports


def test_domain_modules_do_not_depend_on_agent():
    for app_name in ("inventory", "replenishment", "purchasing"):
        for path in python_modules(app_name):
            assert not any(
                module == "apps.agent" or module.startswith("apps.agent.")
                for module in imported_modules(path)
            ), f"{path} must not depend on apps.agent"
