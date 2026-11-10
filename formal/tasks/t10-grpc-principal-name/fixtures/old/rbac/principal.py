"""Authenticated principals in xDS RBAC policies."""


def principal_name_matches(cert, matcher):
    """Whether `authenticated.principal_name` matches this client certificate."""
    if cert is None:
        return matcher.matches("")
    if cert.uri_sans:
        return any(matcher.matches(value) for value in cert.uri_sans)
    if cert.dns_sans:
        return any(matcher.matches(value) for value in cert.dns_sans)
    return matcher.matches(cert.subject)
