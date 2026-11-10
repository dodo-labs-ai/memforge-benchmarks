from kestrel.alerts import ack_deadline_seconds


def is_overdue(raised_at: float, now: float) -> bool:
    """Whether an alert raised at `raised_at` has passed its acknowledgement deadline."""
    return now - raised_at > ack_deadline_seconds()
