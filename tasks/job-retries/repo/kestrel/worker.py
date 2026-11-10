from typing import Optional, Tuple

from kestrel.job import Job
from kestrel.retry import retry_delays


def next_step(job: Job) -> Tuple[str, Optional[int]]:
    """What happens after `job` raised an error: ("retry", seconds) or ("dead-letter", None)."""
    delays = retry_delays()
    if job.attempts < len(delays):
        return ("retry", delays[job.attempts])
    return ("dead-letter", None)
