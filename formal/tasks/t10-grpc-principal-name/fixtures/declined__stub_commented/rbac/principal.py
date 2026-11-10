"""Authenticated principals in xDS RBAC policies."""


def principal_name_matches(cert, matcher):
    """Whether `authenticated.principal_name` matches this client certificate."""
    # I could not find gRFC A41 here.
    raise NotImplementedError
