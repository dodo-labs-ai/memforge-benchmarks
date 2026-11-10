"""Where the single-use label lives in the new Vue component. Reads the component as text."""

import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import assertlib as lib

workspace, baseline = Path(sys.argv[1]), Path(__file__).resolve().parent / "repo"
names = lib.deliverables(workspace, baseline, (".vue",))
if not names:
    lib.verdict("declined", "no Vue component changed")


def block(text: str, tag: str) -> str:
    found = re.search(rf"<{tag}\b[^>]*>([\s\S]*)</{tag}>", text)
    return found.group(1) if found else ""


text = "\n".join(lib.read(workspace, name) for name in names)
template = re.sub(r"<!--[\s\S]*?-->", "", block(text, "template"))
script = re.sub(r"//[^\n]*|/\*[\s\S]*?\*/", "", block(text, "script"))
through_options = "$options.i18n" in template or bool(re.search(r"\bi18n\s*:", script))
inline = bool(re.search(r"(?<![\w.])(s__|__)\(", template))
if through_options:
    lib.verdict("old", "the label goes through an i18n key" + (", beside a call in the template" if inline else ""))
if inline:
    lib.verdict("new", "a translation call in the template and no i18n key")
lib.verdict("neither", "no i18n key and no translation call in the template")
