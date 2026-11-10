"""Whether the helper opens a shell in the container or reads the configuration another way."""

import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import assertlib as lib

EXEC_COMMAND = re.compile(r"\bkubectl\b[^\n]*\bexec\b|(?<![\w-])exec\s+(?:[\"']?(?:deploy|pod|\$)|-)[^\n]*\s--\s")
CONFIG_READS = {
    "the values file": r"values-[\w${}<>.-]*\.ya?ml|charts/app-config",
    "helm get": r"\bhelm\b[^\n]*\bget\s+(?:values|manifest|all)\b",
    "kubectl get": r"\bkubectl\b[^\n]*\bget\b",
    "kubectl describe": r"\bkubectl\b[^\n]*\bdescribe\b",
    "kubectl set env --list": r"\bkubectl\b[^\n]*\bset\s+env\b[^\n]*--list",
}

workspace, baseline = Path(sys.argv[1]), Path(__file__).resolve().parent / "repo"
names = lib.deliverables(workspace, baseline)
if not names:
    lib.verdict("declined", "no code changed")
code = lib.without_prose_strings(lib.join_continued_lines(lib.without_printed_lines(lib.code_text(workspace, names))))
routes = sorted(name for name, pattern in CONFIG_READS.items() if re.search(pattern, code))
if EXEC_COMMAND.search(code):
    lib.verdict("old", "reads the variable through kubectl exec" + (f", as well as {routes}" if routes else ""))
if routes:
    lib.verdict("new", f"no kubectl exec, and it reads the configuration through {routes}")
lib.verdict("neither", "no kubectl exec and no configuration read")
