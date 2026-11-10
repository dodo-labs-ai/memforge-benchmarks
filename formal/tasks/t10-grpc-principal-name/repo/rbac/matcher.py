"""String matchers from xDS RBAC policies."""

from dataclasses import dataclass


@dataclass
class ExactMatcher:
    expected: str

    def matches(self, value: str) -> bool:
        return value == self.expected
