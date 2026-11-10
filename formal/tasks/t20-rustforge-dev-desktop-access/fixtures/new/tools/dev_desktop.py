"""Helpers for dev desktops."""


def access_request(github_handle, use_case):
    return {"channel": "pull_request", "destination": "rust-lang/team", "body": f"Add {github_handle} to cloud-compute: {use_case}"}
