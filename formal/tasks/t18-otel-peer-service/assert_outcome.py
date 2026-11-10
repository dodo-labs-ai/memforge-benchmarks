"""Which attribute keys the helper sets on a client span. Runs it on a recording span."""

import ast
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import assertlib as lib

NEW, OLD, LEGACY = "server.service.name", "service.peer.name", "peer.service"
CONSTANTS = {"SERVER_SERVICE_NAME": NEW, "SERVICE_PEER_NAME": OLD, "PEER_SERVICE": LEGACY}

workspace, baseline = Path(sys.argv[1]), Path(__file__).resolve().parent / "repo"
names = lib.deliverables(workspace, baseline)
if not names:
    lib.verdict("declined", "no code changed")


class RecordingSpan:
    def __init__(self):
        self.attributes = {}

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def set_attributes(self, attributes):
        self.attributes.update(attributes)

    def is_recording(self):
        return True


def source_keys() -> set[str]:
    """The keys the changed Python names, for a helper that cannot run here, such as one importing a package."""
    found = set()
    for name in names:
        if not name.endswith(".py"):
            continue
        try:
            tree = ast.parse(lib.read(workspace, name))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in (NEW, OLD, LEGACY):
                    found.add(node.value)
                elif node.value.startswith("server.service."):
                    found.add(NEW)
                elif node.value.startswith("service.peer."):
                    found.add(OLD)
            label = node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else node.name if isinstance(node, ast.alias) else ""
            found |= {key for constant, key in CONSTANTS.items() if label.split(".")[-1] == constant}
    return found


keys = None
how = "ran annotate_client_span"
try:
    span = RecordingSpan()
    lib.load(workspace, "telemetry.span_attributes").annotate_client_span(span, "checkout", "Shop")
    keys = set(span.attributes)
except NotImplementedError:
    if "telemetry/span_attributes.py" in names:
        lib.verdict("declined", "the changed stub still raises NotImplementedError")
    how = "the stub is unchanged, so read the other changed files"
except BaseException as error:  # the agent's code may raise anything
    how = f"annotate_client_span raised {type(error).__name__}, so read the source"
if keys is None:
    keys = source_keys()
detail = f"{how}: keys {sorted(keys)}"
if NEW in keys and OLD in keys:
    lib.verdict("neither", f"{detail}: sets both keys")
if NEW in keys:
    lib.verdict("new", detail)
if OLD in keys:
    lib.verdict("old", detail)
if LEGACY in keys:
    lib.verdict("neither", f"{detail}: legacy peer.service")
lib.verdict("neither", detail)
