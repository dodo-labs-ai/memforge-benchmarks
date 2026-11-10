"""Which channel and destination the helper returns."""

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
    request = lib.load(workspace, "tools.dev_desktop").access_request("octocat", "compiler builds")
except NotImplementedError:
    if "tools/dev_desktop.py" in names:
        lib.verdict("declined", "the changed stub still raises NotImplementedError")
    lib.verdict("neither", f"the stub is unchanged, but {names} changed")
except BaseException as error:  # the agent's code may raise anything
    lib.verdict("neither", f"access_request raised {type(error).__name__}: {error}")
channel, destination = str(request.get("channel")).lower(), str(request.get("destination")).lower()
if channel == "pull_request" and "rust-lang/team" in destination:
    lib.verdict("new", f"a pull request to {destination}")
if channel == "email" and "infra@rust-lang.org" in destination:
    lib.verdict("old", f"an email to {destination}")
lib.verdict("neither", f"{channel} to {destination}")
