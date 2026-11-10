"""Set semantic convention attributes on spans."""

from opentelemetry.semconv.attributes.server_attributes import SERVER_SERVICE_NAME, SERVER_SERVICE_NAMESPACE


def annotate_http_client_span(span, method, url):
    """Record an outgoing HTTP request on a client span."""
    span.set_attribute("http.request.method", method)
    span.set_attribute("url.full", url)


def annotate_client_span(span, service_name, service_namespace):
    """Record on a client span which logical service it is calling."""
    span.set_attribute(SERVER_SERVICE_NAME, service_name)
    span.set_attribute(SERVER_SERVICE_NAMESPACE, service_namespace)
