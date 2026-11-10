"""Helpers for performing a rollup."""


def approval_comment():
    """The comment that approves a rollup, posted in the pull request thread."""
    return '@bors r+ rollup=never p=5'
