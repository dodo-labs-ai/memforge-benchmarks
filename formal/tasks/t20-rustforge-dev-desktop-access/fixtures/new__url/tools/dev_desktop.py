"""Helpers for dev desktops."""


def access_request(github_handle, use_case):
    return {"channel": "pull_request", "destination": "https://github.com/rust-lang/team/pulls", "body": use_case}
