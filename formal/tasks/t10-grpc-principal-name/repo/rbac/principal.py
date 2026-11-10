"""Authenticated principals in xDS RBAC policies."""


def principal_name_matches(cert, matcher):
    """Whether `authenticated.principal_name` matches this client certificate."""
    raise NotImplementedError
