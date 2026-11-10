"""Which warning class the deprecation names. Walks the syntax tree, so comments do not count."""

import ast
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import assertlib as lib

# The new revision gives only the pattern, and the old one only its own, so a name that
# follows either pattern counts, the literal placeholder included.
NEW = re.compile(r"^RemovedInDjango(\d{4}|XXXX)Warning$")
OLD = re.compile(r"^RemovedInDjango(\d{2}|XX)Warning$")

workspace, baseline = Path(sys.argv[1]), Path(__file__).resolve().parent / "repo"
names = lib.deliverables(workspace, baseline, (".py",))
if not names:
    lib.verdict("declined", "no Python changed")

identifiers: set[str] = set()
for name in names:
    text = lib.read(workspace, name)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        identifiers |= set(re.findall(r"\bRemovedInDjango\w+Warning\b", lib.strip_hash_comments(text)))
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, ast.alias):
            identifiers.add(node.name.split(".")[-1])
        elif isinstance(node, ast.ClassDef):
            identifiers.add(node.name)

new = sorted(item for item in identifiers if NEW.match(item))
old = sorted(item for item in identifiers if OLD.match(item))
if new and old:
    lib.verdict("neither", f"names both kinds: {new + old}")
if new:
    lib.verdict("new", f"names {new}")
if old:
    lib.verdict("old", f"names {old}")
other = sorted(item for item in identifiers if item.endswith("Warning"))
lib.verdict("neither", f"names no versioned warning class; warnings named: {other}")
