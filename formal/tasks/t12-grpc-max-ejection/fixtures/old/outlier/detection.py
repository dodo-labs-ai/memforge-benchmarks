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
    settings = config.failure_percentage_ejection
    eligible = [a for a in addresses if a.successes + a.failures >= settings.request_volume]
    if len(eligible) < settings.minimum_hosts:
        return []
    done = []
    for address in addresses:
        if 100 * sum(a.ejected for a in addresses) / len(addresses) >= config.max_ejection_percent:
            break
        total = address.successes + address.failures
        if total < settings.request_volume:
            continue
        if 100 * address.failures / total > settings.threshold and randint() < settings.enforcement_percentage:
            address.ejected = True
            done.append(address.name)
    return done
