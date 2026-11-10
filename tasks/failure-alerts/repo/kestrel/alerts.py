"""Failure alerts for Kestrel jobs."""


def alert_channel() -> str:
    """Where a failure alert is sent."""
    raise NotImplementedError


def ack_deadline_seconds() -> int:
    """How long the on-call engineer has to acknowledge a failure alert, in seconds."""
    raise NotImplementedError
