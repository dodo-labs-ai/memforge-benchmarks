"""The retry schedule for failed jobs."""

from typing import List


def retry_delays() -> List[int]:
    """Seconds to wait before each retry of a failed job, in order.

    The length of the list is the number of retries.
    """
    raise NotImplementedError
