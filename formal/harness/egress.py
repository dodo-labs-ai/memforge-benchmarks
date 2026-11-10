"""What a run's Codex process connects to.

Two records, because either alone misses something:

- A logging proxy, one per run, that Codex is pointed at through its environment. It names
  every host Codex asks for. It forwards to the machine's own proxy when there is one, so
  the route to the model stays the one the machine already uses. Shell commands in a run
  do not see these variables, because the run's environment policy passes only core ones.
- A poll of the run's process group with `lsof` every half second, for any socket that goes
  around that proxy. A connection that opens and closes between two polls is not seen.

The endpoint's host is only ever recorded as `endpoint`, so it never reaches a result. Every
other host is recorded by name and flagged in the screen's summary.
"""

from __future__ import annotations

import ipaddress
import re
import select
import socket
import subprocess
import threading
import time

POLL_SECONDS = 0.5
_REMOTE = re.compile(r"->(?:\[(?P<v6>[^\]]+)\]|(?P<v4>[^:]+)):(?P<port>\d+|\*)$")
_HEADER_END = b"\r\n\r\n"
_MAX_HEADER = 65536


def machine_proxy() -> tuple[str, int] | None:
    """The HTTPS proxy this machine's own settings name, if any."""
    try:
        output = subprocess.run(["/usr/sbin/scutil", "--proxy"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    fields = dict(re.findall(r"^\s*(HTTPS\w+)\s*:\s*(\S+)\s*$", output, flags=re.MULTILINE))
    if fields.get("HTTPSEnable") != "1" or "HTTPSProxy" not in fields or "HTTPSPort" not in fields:
        return None
    return fields["HTTPSProxy"], int(fields["HTTPSPort"])


def _pump(one: socket.socket, other: socket.socket) -> None:
    """Copy bytes both ways until either side closes."""
    sockets = [one, other]
    try:
        while True:
            readable, _, broken = select.select(sockets, [], sockets, 600)
            if broken or not readable:
                return
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return
                (other if source is one else one).sendall(data)
    except OSError:
        return


def _read_head(connection: socket.socket) -> bytes:
    head = b""
    while _HEADER_END not in head and len(head) < _MAX_HEADER:
        chunk = connection.recv(4096)
        if not chunk:
            break
        head += chunk
    return head


class LoggingProxy:
    """A CONNECT proxy on loopback that counts the hosts asked for."""

    def __init__(self, endpoint_host: str | None, upstream: tuple[str, int] | None) -> None:
        self.endpoint_host = endpoint_host
        self.upstream = upstream
        self.hosts: dict[str, int] = {}
        self.errors = 0
        self._lock = threading.Lock()
        self._server = socket.create_server(("127.0.0.1", 0))
        self.port = self._server.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def env(self) -> dict[str, str]:
        url = f"http://127.0.0.1:{self.port}"
        return {
            "HTTPS_PROXY": url, "https_proxy": url, "HTTP_PROXY": url, "http_proxy": url, "ALL_PROXY": url, "all_proxy": url,
            "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
        }

    def _count(self, host: str, port: int) -> None:
        label = "endpoint" if host == self.endpoint_host else f"{host}:{port}"
        with self._lock:
            self.hosts[label] = self.hosts.get(label, 0) + 1

    def _serve(self) -> None:
        while True:
            try:
                connection, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(connection,), daemon=True).start()

    def _open_tunnel(self, host: str, port: int) -> socket.socket:
        if self.upstream is None:
            return socket.create_connection((host, port), timeout=30)
        upstream = socket.create_connection(self.upstream, timeout=30)
        upstream.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode())
        answer = _read_head(upstream)
        if not re.match(rb"HTTP/1\.[01] 200", answer):
            upstream.close()
            raise OSError("the machine's proxy refused the tunnel")
        return upstream

    def _handle(self, connection: socket.socket) -> None:
        upstream = None
        try:
            head = _read_head(connection)
            first = head.split(b"\r\n", 1)[0].decode("latin-1").split(" ")
            if len(first) < 2:
                return
            method, target = first[0], first[1]
            if method == "CONNECT":
                host, _, port = target.rpartition(":")
                self._count(host, int(port))
                upstream = self._open_tunnel(host, int(port))
                upstream.settimeout(None)
                connection.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            else:
                found = re.match(r"http://([^/:]+)(?::(\d+))?", target)
                if not found:
                    return
                host, port = found.group(1), int(found.group(2) or 80)
                self._count(host, port)
                upstream = socket.create_connection(self.upstream or (host, port), timeout=30)
                upstream.settimeout(None)
                upstream.sendall(head)
            _pump(connection, upstream)
        except (OSError, ValueError):
            with self._lock:
                self.errors += 1
        finally:
            connection.close()
            if upstream is not None:
                upstream.close()

    def close(self) -> None:
        self._server.close()


def remote_endpoints(lsof_output: str) -> set[tuple[str, str]]:
    """Every (address, port) a `lsof -F n` listing holds as the far end of a socket."""
    found = set()
    for line in lsof_output.splitlines():
        if not line.startswith("n"):
            continue
        match = _REMOTE.search(line[1:])
        if match:
            found.add((match["v6"] or match["v4"], match["port"]))
    return found


def _label(address: str, port: str) -> str:
    try:
        loopback = ipaddress.ip_address(address).is_loopback
    except ValueError:
        loopback = False
    return f"loopback:{port}" if loopback else f"{address}:{port}"


class Watch:
    """The poll of one process group, and the proxy it runs behind, until `stop`."""

    def __init__(self, process_group: int, proxy: LoggingProxy) -> None:
        self.process_group = process_group
        self.proxy = proxy
        self.polls = 0
        self.failed_polls = 0
        self.around_the_proxy: set[str] = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _poll(self) -> None:
        result = subprocess.run(
            ["/usr/sbin/lsof", "-nP", "-a", "-g", str(self.process_group), "-i", "-F", "n"],
            capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL,
        )
        self.polls += 1
        # lsof exits 1 when the group holds no socket, which is an answer, not a failure.
        if result.returncode not in (0, 1):
            self.failed_polls += 1
        for address, port in remote_endpoints(result.stdout):
            if port != str(self.proxy.port):
                self.around_the_proxy.add(_label(address, port))

    def _run(self) -> None:
        while not self._stop.is_set():
            begun = time.monotonic()
            try:
                self._poll()
            except (OSError, subprocess.SubprocessError):
                self.failed_polls += 1
            self._stop.wait(max(0.0, POLL_SECONDS - (time.monotonic() - begun)))

    def stop(self) -> dict:
        self._stop.set()
        self._thread.join(timeout=15)
        self.proxy.close()
        hosts = dict(self.proxy.hosts)
        return {
            "connections_to_the_endpoint": hosts.pop("endpoint", 0),
            "other_hosts": sorted(hosts),
            "sockets_around_the_proxy": sorted(self.around_the_proxy),
            "proxy_errors": self.proxy.errors,
            "polls": self.polls,
            "failed_polls": self.failed_polls,
        }
