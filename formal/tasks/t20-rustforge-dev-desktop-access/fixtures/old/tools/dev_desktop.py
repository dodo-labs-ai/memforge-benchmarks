"""Helpers for dev desktops."""


def access_request(github_handle, use_case):
    return {"channel": "email", "destination": "infra@rust-lang.org", "body": f"{github_handle}: {use_case}"}
