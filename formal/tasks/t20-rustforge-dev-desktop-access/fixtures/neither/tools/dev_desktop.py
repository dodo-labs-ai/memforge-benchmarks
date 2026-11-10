"""Helpers for dev desktops."""


def access_request(github_handle, use_case):
    return {"channel": "issue", "destination": "rust-lang/infra-team", "body": use_case}
