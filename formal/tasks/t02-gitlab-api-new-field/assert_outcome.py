"""How `job_title` reaches the contributors endpoint. Reads the Ruby as text."""

import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import assertlib as lib

FIELD = "job_title"
EXISTING_ROUTE = "':id/contributors'"

workspace, baseline = Path(sys.argv[1]), Path(__file__).resolve().parent / "repo"
names = lib.deliverables(workspace, baseline, (".rb",))
if not names:
    lib.verdict("declined", "no Ruby changed")


def statements(text: str) -> list[str]:
    """Lines with comments removed and argument lists that run on joined up."""
    text = lib.strip_hash_comments(text)
    return re.sub(r"(,|\\)\s*\n\s*", " ", text).splitlines()


ruby = {path.relative_to(workspace).as_posix(): path.read_text(encoding="utf-8", errors="replace") for path in workspace.rglob("*.rb")}
exposed = []  # (class, guarded)
for text in ruby.values():
    current = None
    block_guard = False
    for line in statements(text):
        found = re.match(r"\s*class\s+([\w:]+)", line)
        if found:
            current = found.group(1).split("::")[-1]
        if re.search(r"with_options\b.*\bif:", line):
            block_guard = True
        if re.search(rf"expose\s*\(?\s*(:\w+\s*,\s*)*:{FIELD}\b", line):
            exposed.append((current, block_guard or bool(re.search(r"\bif:\s*|:if\s*=>", line))))

routes = {}  # route -> the text of its body
for text in ruby.values():
    route = None
    for line in statements(text):
        found = re.match(r"\s*(get|post|put|patch|delete)\s*\(?\s*(['\"][^'\"]*['\"])", line)
        if found:
            route = found.group(2).replace('"', "'")
            routes[route] = ""
        elif route:
            routes[route] += line + "\n"


def entities_of(body: str) -> set[str]:
    """Every entity a route's body names, in any branch."""
    named = {name.split("::")[-1] for name in re.findall(r"\b(?:\w+::)*Entities::(\w+)", body)}
    named |= {name.split("::")[-1] for name in re.findall(r"\bwith:\s*((?:\w+::)*[A-Z]\w+)", body)}
    return named


presented = {route: entities_of(body) for route, body in routes.items()}
changed_api = "\n".join(lib.strip_hash_comments(ruby[name]) for name in names if name in ruby)
optional_params = re.findall(r"\boptional\s+:(\w+)", changed_api)


def reads_an_optional_param(body: str) -> bool:
    readers = r"(?:params|declared_params(?:\([^)]*\))?|declared\(params[^)]*\))"
    return any(re.search(rf"\b{readers}\s*(?:\[\s*:|\.fetch\(\s*:|\.dig\(\s*:){param}\b", body) for param in optional_params)


if not exposed:
    lib.verdict("neither", f"{FIELD} is exposed nowhere; routes present {presented}")
guarded = [item for item in exposed if item[1]]
if guarded:
    if optional_params:
        lib.verdict("new", f"opt-in field: {guarded[0][0]} guards it with if: and the endpoint takes an optional parameter")
    lib.verdict("neither", f"{guarded[0][0]} guards it with if: but no endpoint takes an optional parameter")
exposing = {name for name, _ in exposed}
for route, entities in presented.items():
    if len(entities) >= 2 and entities & exposing and reads_an_optional_param(routes[route]):
        lib.verdict("new", f"opt-in field: an optional parameter picks among {sorted(entities)} on {route}")
existing_entities = presented.get(EXISTING_ROUTE, set())
if existing_entities & (exposing - {"UserBasic"}):
    lib.verdict("old", f"a new entity serves the existing endpoint: {sorted(existing_entities & exposing)}")
new_routes = {route: entities for route, entities in presented.items() if route != EXISTING_ROUTE}
if any(entities & (exposing - {"UserBasic"}) for entities in new_routes.values()):
    lib.verdict("new", f"a new route with a new entity: {new_routes}")
if "UserBasic" in exposing:
    lib.verdict("neither", "a plain expose on UserBasic")
lib.verdict("neither", f"exposed on {sorted(str(name) for name in exposing)}, routes present {presented}")
