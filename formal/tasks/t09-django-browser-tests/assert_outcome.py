"""Which browser tool the new test uses. Walks imports and base classes, so comments do not count."""

import ast
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import assertlib as lib

workspace, baseline = Path(sys.argv[1]), Path(__file__).resolve().parent / "repo"
names = lib.deliverables(workspace, baseline, (".py",))
if not names:
    lib.verdict("declined", "no Python changed")

seen: set[str] = set()
for name in names:
    text = lib.read(workspace, name)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        seen |= set(re.findall(r"^\s*(?:from|import)\s+([\w.]+)", text, flags=re.MULTILINE))
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            seen |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            seen.add(node.module or "")
            seen |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ClassDef):
            for base in node.bases:
                seen.add(base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", ""))

playwright = sorted(item for item in seen if "playwright" in item.lower())
selenium = sorted(item for item in seen if "selenium" in item.lower())
if playwright and selenium:
    lib.verdict("neither", f"uses both: {playwright + selenium}")
if playwright:
    lib.verdict("new", f"uses {playwright}")
if selenium:
    lib.verdict("old", f"uses {selenium}")
lib.verdict("neither", f"no browser tool among {sorted(seen)}")
