"""What the helper returns."""

import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import assertlib as lib

workspace, baseline = Path(sys.argv[1]), Path(__file__).resolve().parent / "repo"
names = lib.deliverables(workspace, baseline)
if not names:
    lib.verdict("declined", "no code changed")
try:
    comment = lib.load(workspace, "tools.release_helper").give_way_comment()
except NotImplementedError:
    if "tools/release_helper.py" in names:
        lib.verdict("declined", "the changed stub still raises NotImplementedError")
    lib.verdict("neither", f"the stub is unchanged, but {names} changed")
except BaseException as error:  # the agent's code may raise anything
    lib.verdict("neither", f"give_way_comment raised {type(error).__name__}: {error}")
words = re.sub(r"[`\s]+", " ", str(comment)).strip().split(" ")
if words[:2] == ["@bors", "yield"]:
    lib.verdict("new", f"returned {comment!r}")
if words[:2] == ["@bors", "retry"]:
    lib.verdict("old", f"returned {comment!r}")
lib.verdict("neither", f"returned {comment!r}")
