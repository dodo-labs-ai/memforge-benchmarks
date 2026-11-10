"""One pass of outlier detection over a load balancing policy's addresses."""

from dataclasses import dataclass, field


@dataclass
class Address:
    name: str
    successes: int = 0
    failures: int = 0
    ejected: bool = False


@dataclass
class FailurePercentageEjection:
    threshold: int = 85
    enforcement_percentage: int = 100
    minimum_hosts: int = 5
    request_volume: int = 50


@dataclass
class OutlierDetectionConfig:
    max_ejection_percent: int = 10
    failure_percentage_ejection: FailurePercentageEjection = field(default_factory=FailurePercentageEjection)


def run_failure_percentage_ejection(addresses, config, randint):
    """Run one pass of the failure percentage algorithm.

    `randint()` returns a random integer in [0, 100).
    """
    raise NotImplementedError
