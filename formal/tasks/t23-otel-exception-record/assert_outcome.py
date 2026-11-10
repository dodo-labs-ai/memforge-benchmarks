"""Whether the helper records the error as a span event or a log record. Runs it on recording objects."""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import assertlib as lib

workspace, baseline = Path(sys.argv[1]), Path(__file__).resolve().parent / "repo"
names = lib.deliverables(workspace, baseline)
if not names:
    lib.verdict("declined", "no code changed")


class RecordingSpan:
    def __init__(self):
        self.events = []

    def record_exception(self, exception, *args, **kwargs):
        self.events.append("record_exception")

    def add_event(self, name, *args, **kwargs):
        self.events.append(name)

    def set_attribute(self, key, value):
        pass

    def set_attributes(self, attributes):
        pass

    def set_status(self, *args, **kwargs):
        pass

    def is_recording(self):
        return True


class RecordingLogger:
    def __init__(self):
        self.records = 0

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.records += 1

        if name in ("debug", "info", "warning", "warn", "error", "exception", "critical", "fatal", "log"):
            return record
        raise AttributeError(name)


span, logger = RecordingSpan(), RecordingLogger()
try:
    lib.load(workspace, "telemetry.errors").record_operation_error(span, logger, ValueError("boom"))
except NotImplementedError:
    if "telemetry/errors.py" in names:
        lib.verdict("declined", "the changed stub still raises NotImplementedError")
    lib.verdict("neither", f"the stub is unchanged, but {names} changed")
except BaseException as error:  # the agent's code may raise anything
    lib.verdict("neither", f"record_operation_error raised {type(error).__name__}: {error}")
detail = f"span events {span.events}, {logger.records} log records"
if span.events:
    lib.verdict("old", detail)
if logger.records:
    lib.verdict("new", detail)
lib.verdict("neither", detail)
