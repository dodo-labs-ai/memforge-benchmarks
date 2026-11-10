"""Which attribute key the helper sets. Runs it on a recording span."""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import assertlib as lib

workspace, baseline = Path(sys.argv[1]), Path(__file__).resolve().parent / "repo"
names = lib.deliverables(workspace, baseline)
if not names:
    lib.verdict("declined", "no code changed")

NEW, OLD = "rpc.status_code", "rpc.response.status_code"


class RecordingSpan:
    def __init__(self):
        self.attributes = {}

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def set_attributes(self, attributes):
        self.attributes.update(attributes)

    def is_recording(self):
        return True


try:
    span = RecordingSpan()
    lib.load(workspace, "telemetry.span_attributes").annotate_rpc_result(span, "NOT_FOUND")
except NotImplementedError:
    if "telemetry/span_attributes.py" in names:
        lib.verdict("declined", "the changed stub still raises NotImplementedError")
    lib.verdict("neither", f"the stub is unchanged, but {names} changed")
except BaseException as error:  # the agent's code may raise anything
    lib.verdict("neither", f"annotate_rpc_result raised {type(error).__name__}: {error}")
keys = set(span.attributes)
detail = f"keys {sorted(keys)}"
if NEW in keys and OLD in keys:
    lib.verdict("neither", f"{detail}: sets both keys")
if NEW in keys:
    lib.verdict("new", detail)
if OLD in keys:
    lib.verdict("old", detail)
lib.verdict("neither", detail)
