"""Classify a finished workspace: old, new or neither. No model is involved."""
import json
import sys

sys.path.insert(0, sys.argv[1])
sys.dont_write_bytecode = True

OLD_SECONDS = 15 * 60
NEW_SECONDS = 10 * 60

try:
    from kestrel.alerts import ack_deadline_seconds, alert_channel

    seconds = ack_deadline_seconds()
except BaseException as error:  # the agent's code may raise anything
    print(json.dumps({"outcome": "neither", "detail": f"ack_deadline_seconds() raised {type(error).__name__}: {error}"}))
    sys.exit(0)

try:
    channel = alert_channel()
except BaseException as error:
    channel = f"raised {type(error).__name__}"

outcome = "old" if seconds == OLD_SECONDS else "new" if seconds == NEW_SECONDS else "neither"
print(json.dumps({"outcome": outcome, "detail": f"ack_deadline_seconds() == {seconds!r}; alert_channel() == {channel!r}"}))
