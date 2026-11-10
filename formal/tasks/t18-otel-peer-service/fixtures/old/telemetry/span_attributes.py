"""Set semantic convention attributes on spans."""


def annotate_http_client_span(span, method, url):
    """Record an outgoing HTTP request on a client span."""
    span.set_attribute("http.request.method", method)
    span.set_attribute("url.full", url)


def annotate_client_span(span, service_name, service_namespace):
    """Record on a client span which logical service it is calling."""
    span.set_attribute("service.peer.name", service_name)
    span.set_attribute("service.peer.namespace", service_namespace)
