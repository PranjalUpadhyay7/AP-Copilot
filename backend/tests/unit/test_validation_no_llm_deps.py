import ast
from pathlib import Path

VALIDATION_DIR = Path(__file__).resolve().parents[2] / "app" / "validation"

FORBIDDEN_MODULE_PREFIXES = ("langchain", "langgraph", "openai", "langsmith")


def _imported_module_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_no_llm_orchestration_imports_anywhere_in_validation_package():
    py_files = list(VALIDATION_DIR.glob("*.py"))
    assert py_files, "expected to find validation module source files"

    offenders = {}
    for path in py_files:
        roots = _imported_module_roots(path)
        hit = roots & set(FORBIDDEN_MODULE_PREFIXES)
        if hit:
            offenders[path.name] = hit

    assert not offenders, f"Validation Layer must be LLM-free, found: {offenders}"
