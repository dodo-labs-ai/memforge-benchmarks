"""Set semantic convention attributes on spans."""


def annotate_http_client_span(span, method, url):
    """Record an outgoing HTTP request on a client span."""
    span.set_attribute("http.request.method", method)
    span.set_attribute("url.full", url)


def annotate_rpc_result(span, code):
    """Record the status code of a finished RPC on its span."""
    raise NotImplementedError
