"""Record errors from instrumented operations."""


def record_operation_error(span, logger, error):
    logger.error("operation failed", exc_info=error)
