"""Record errors from instrumented operations."""


def record_operation_error(span, logger, error):
    span.set_attribute("error.type", type(error).__name__)
