"""The parts of a client certificate that RBAC looks at."""

from dataclasses import dataclass, field


@dataclass
class Certificate:
    uri_sans: list[str] = field(default_factory=list)
    dns_sans: list[str] = field(default_factory=list)
    # The Subject's distinguished name, formatted as an RFC 2253 name.
    subject: str = ""
