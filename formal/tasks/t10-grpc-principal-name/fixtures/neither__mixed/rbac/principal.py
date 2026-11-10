"""Authenticated principals in xDS RBAC policies."""


def principal_name_matches(cert, matcher):
    """Whether `authenticated.principal_name` matches this client certificate."""
    if cert is None:
        return matcher.matches("")
    if any(matcher.matches(value) for value in cert.uri_sans) or any(matcher.matches(value) for value in cert.dns_sans):
        return True
    if cert.uri_sans or cert.dns_sans:
        return False
    return matcher.matches(cert.subject)
