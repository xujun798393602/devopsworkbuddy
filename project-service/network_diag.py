"""Run non-destructive Docker Registry network diagnostics."""

import socket
import ssl
import urllib.parse
import urllib.request

HOSTS: tuple[str, ...] = (
    "auth.docker.io",
    "registry-1.docker.io",
    "mirror.gcr.io",
)
ENDPOINTS: tuple[tuple[str, str], ...] = (
    (
        "auth.docker.io",
        "/token?service=registry.docker.io&scope=repository:library/python:pull",
    ),
    ("registry-1.docker.io", "/v2/"),
    ("mirror.gcr.io", "/v2/library/python/manifests/3.13-slim"),
)


def main() -> None:
    """Print DNS, TLS, HTTP, and proxy diagnostics without changing system state."""
    for host in HOSTS:
        addresses = {
            (result[0], result[4][0])
            for result in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        }
        print(host, sorted(addresses))

    for host, path in ENDPOINTS:
        for family, label in ((socket.AF_INET, "ipv4"), (socket.AF_INET6, "ipv6")):
            try:
                address_info = socket.getaddrinfo(host, 443, family, socket.SOCK_STREAM)
                socket_connection = socket.create_connection(address_info[0][4], timeout=10)
                context = ssl.create_default_context()
                with context.wrap_socket(socket_connection, server_hostname=host) as tls:
                    request = (
                        f"GET {path} HTTP/1.1\r\n"
                        f"Host: {host}\r\n"
                        "Connection: close\r\n"
                        "Accept: application/json\r\n\r\n"
                    )
                    tls.sendall(request.encode())
                    status_line = tls.recv(256).split(b"\r\n", 1)[0].decode(errors="replace")
                    print(host, label, status_line)
            except (OSError, ssl.SSLError) as error:
                print(host, label, type(error).__name__, str(error)[:120])

    proxies = {
        key: urllib.parse.urlparse(value).hostname
        for key, value in urllib.request.getproxies().items()
    }
    print("urllib proxies", proxies)


if __name__ == "__main__":
    main()
