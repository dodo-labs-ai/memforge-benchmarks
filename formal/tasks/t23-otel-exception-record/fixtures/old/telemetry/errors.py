"""Record errors from instrumented operations."""


def record_operation_error(span, logger, error):
    span.record_exception(error)
