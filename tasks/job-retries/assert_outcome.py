"""Classify a finished workspace: old, new or neither. No model is involved."""
import json
import sys

sys.path.insert(0, sys.argv[1])
sys.dont_write_bytecode = True

OLD = [10, 60, 300]
NEW = [10, 60, 300, 900, 3600]

try:
    from kestrel.retry import retry_delays

    delays = retry_delays()
except BaseException as error:  # the agent's code may raise anything
    print(json.dumps({"outcome": "neither", "detail": f"retry_delays() raised {type(error).__name__}: {error}"}))
    sys.exit(0)

delays = list(delays) if isinstance(delays, (list, tuple)) else delays
outcome = "old" if delays == OLD else "new" if delays == NEW else "neither"
print(json.dumps({"outcome": outcome, "detail": f"retry_delays() == {delays!r}"}))
