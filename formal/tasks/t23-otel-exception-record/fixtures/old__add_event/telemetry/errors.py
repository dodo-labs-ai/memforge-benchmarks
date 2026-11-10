"""Record errors from instrumented operations."""


def record_operation_error(span, logger, error):
    span.add_event("exception", {"exception.message": str(error)})
