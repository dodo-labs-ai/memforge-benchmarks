"""Record errors from instrumented operations."""


def record_operation_error(span, logger, error):
    """What instrumentation records about an error that ended an operation."""
    raise NotImplementedError
