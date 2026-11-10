from dataclasses import dataclass


@dataclass
class Job:
    id: str
    queue: str = "default"
    attempts: int = 0
