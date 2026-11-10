"""Helpers for dev desktops."""


def access_request(github_handle, use_case):
    return {"channel": "email", "destination": "rust-lang/team", "body": use_case}
