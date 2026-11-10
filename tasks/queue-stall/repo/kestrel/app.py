from dataclasses import dataclass
from typing import Callable, List, Tuple

# What a watchdog can observe, in seconds.
METRICS = ("seconds_since_last_job_started", "oldest_pending_job_age", "seconds_since_last_backup")
# What a watchdog can do when its metric passes the threshold.
ACTIONS = ("page_oncall", "post_to_channel", "log")


@dataclass
class QueueConfig:
    data_dir: str = "/var/lib/kestrel"
    journal_mode: str = "wal"
    fsync: bool = True
    busy_timeout_ms: int = 5000
    max_payload_kib: int = 256


class App:
    def __init__(self, config: QueueConfig) -> None:
        self.config = config
        self.startup_checks: List[Callable[[QueueConfig], None]] = []
        self.watchdogs: List[Tuple[str, int, str]] = []

    def add_startup_check(self, check: Callable[[QueueConfig], None]) -> None:
        """Run `check(config)` at startup; it raises to refuse to start."""
        self.startup_checks.append(check)

    def add_watchdog(self, metric: str, threshold_seconds: int, action: str) -> None:
        """Take `action` when `metric` passes `threshold_seconds`."""
        if metric not in METRICS or action not in ACTIONS:
            raise ValueError(f"unknown watchdog {metric!r} {action!r}")
        self.watchdogs.append((metric, threshold_seconds, action))

    def start(self) -> None:
        for check in self.startup_checks:
            check(self.config)
