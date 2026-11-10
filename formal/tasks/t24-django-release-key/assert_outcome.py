"""Where the script gets the key from."""

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

KEYSERVER = re.compile(r"--recv-keys?\b|--keyserver\b|--search-keys\b")
GITHUB = re.compile(r"github\.com/\S*\.gpg|api\.github\.com/users/\S*gpg_keys|\bgh\s+api\b[^\n]*gpg_keys")

code = lib.without_prose_strings(lib.join_continued_lines(lib.without_printed_lines(lib.code_text(workspace, names))))
if KEYSERVER.search(code):
    lib.verdict("old", "fetches the key from a keyserver")
if GITHUB.search(code):
    lib.verdict("new", "imports the key from GitHub")
lib.verdict("neither", "no keyserver and no GitHub key import")
