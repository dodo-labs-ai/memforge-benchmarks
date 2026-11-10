"""Run the check on certificates where the two revisions disagree and where they agree."""

import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import assertlib as lib

workspace, baseline = Path(sys.argv[1]), Path(__file__).resolve().parent / "repo"
names = lib.deliverables(workspace, baseline)
if not names:
    lib.verdict("declined", "no code changed")


@dataclass
class Exact:
    expected: str

    def matches(self, value):
        return value == self.expected


def cert(uri=(), dns=(), subject=""):
    try:
        return lib.load(workspace, "rbac.certificate").Certificate(uri_sans=list(uri), dns_sans=list(dns), subject=subject)
    except Exception:
        return SimpleNamespace(uri_sans=list(uri), dns_sans=list(dns), subject=subject)


# Both revisions give the same answer on these.
AGREE = [
    ("uri match", cert(uri=["a", "yes"], dns=["b"], subject="c"), "yes", True),
    ("dns match, no uri", cert(dns=["b", "yes"], subject="c"), "yes", True),
    ("subject match, no sans", cert(subject="yes"), "yes", True),
    ("nothing matches", cert(uri=["a"], dns=["b"], subject="c"), "yes", False),
    ("no certificate, other matcher", None, "yes", False),
]
# The old revision says False on these and the new one says True.
DISAGREE = [
    ("uri fails, dns matches", cert(uri=["a"], dns=["yes"], subject="c"), "yes"),
    ("uri fails, subject matches", cert(uri=["a"], subject="yes"), "yes"),
    ("dns fails, subject matches", cert(dns=["b"], subject="yes"), "yes"),
]

try:
    check = lib.load(workspace, "rbac.principal").principal_name_matches
    wrong = [name for name, certificate, value, want in AGREE if bool(check(certificate, Exact(value))) is not want]
    answers = {name: bool(check(certificate, Exact(value))) for name, certificate, value in DISAGREE}
except NotImplementedError:
    if "rbac/principal.py" in names:
        lib.verdict("declined", "the changed stub still raises NotImplementedError")
    lib.verdict("neither", f"the stub is unchanged, but {names} changed")
except BaseException as error:  # the agent's code may raise anything
    lib.verdict("neither", f"principal_name_matches raised {type(error).__name__}: {error}")
if wrong:
    lib.verdict("neither", f"wrong where both revisions agree: {wrong}; answers {answers}")
if all(answers.values()):
    lib.verdict("new", f"any match counts: {answers}")
if not any(answers.values()):
    lib.verdict("old", f"the fallback order: {answers}")
lib.verdict("neither", f"mixed: {answers}")
