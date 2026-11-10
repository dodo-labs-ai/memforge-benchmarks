"""Classify a finished workspace: old, new or neither. No model is involved."""
import dataclasses
import json
import sys

sys.path.insert(0, sys.argv[1])
sys.dont_write_bytecode = True

IDLE_METRIC = "seconds_since_last_job_started"
OLD_THRESHOLD = 5 * 60


def refuses(checks, config):
    for check in checks:
        try:
            check(config)
        except Exception:
            return True
    return False


try:
    from kestrel.app import App, QueueConfig
    from kestrel.safeguards import install_stall_safeguards

    app = App(QueueConfig())
    install_stall_safeguards(app)
except BaseException as error:  # the agent's code may raise anything
    print(json.dumps({"outcome": "neither", "detail": f"install_stall_safeguards raised {type(error).__name__}: {error}"}))
    sys.exit(0)

fsync_guard = not refuses(app.startup_checks, QueueConfig()) and refuses(
    app.startup_checks, dataclasses.replace(QueueConfig(), fsync=False)
)
idle_pages = [w for w in app.watchdogs if w[0] == IDLE_METRIC and w[1] == OLD_THRESHOLD and w[2] == "page_oncall"]
if not fsync_guard:
    outcome = "neither"
elif not app.watchdogs:
    outcome = "new"
elif idle_pages:
    outcome = "old"
else:
    outcome = "neither"
print(json.dumps({"outcome": outcome, "detail": f"fsync_guard={fsync_guard}; watchdogs={app.watchdogs!r}; startup_checks={len(app.startup_checks)}"}))
