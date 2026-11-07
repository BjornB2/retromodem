#!/usr/bin/env python3
"""Transparent relay for the public RetroWEB HTTP proxy."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import os
import re
import urllib.parse

UPSTREAM_HOST, UPSTREAM_PORT = "retroweb.bjrno.com", 8081
MAX_REQUEST = 1024 * 1024
HOP_HEADERS = {"connection", "proxy-connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade"}


def settings(path="/etc/retromodem/retromodem.env"):
    values = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", line):
                    key, value = line.rstrip("\n").split("=", 1)
                    values[key] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


def requested_url(handler):
    if handler.path.startswith(("http://", "https://")):
        return handler.path
    host = handler.headers.get("Host", "").strip()
    if not host:
        raise ValueError("missing Host header")
    return "http://" + host + (handler.path or "/")


def is_excluded(host, values):
    host = (host or "").lower().rstrip(".")
    entries = re.split(r"[\s,]+", values.get("RETROMODEM_PROXY_EXCEPTIONS", ""))
    return any(host == item.lower().strip(".") or host.endswith("." + item.lower().strip("."))
               for item in entries if item.strip("."))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "RetroModem-OnlineProxy/2.0"

    def do_CONNECT(self):
        self.send_error(501, "Use HTTP URLs; RetroWEB fetches HTTPS upstream")

    def do_GET(self): self.relay()
    def do_HEAD(self): self.relay()
    def do_POST(self): self.relay()

    def relay(self):
        try:
            url = requested_url(self)
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme != "http" or not parsed.hostname:
                raise ValueError("only HTTP URLs are supported")
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_REQUEST or self.headers.get("Transfer-Encoding"):
                self.send_error(413)
                return
            body = self.rfile.read(length) if length else None
            direct = is_excluded(parsed.hostname, settings())
            host = parsed.hostname if direct else UPSTREAM_HOST
            port = (parsed.port or 80) if direct else UPSTREAM_PORT
            target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, "")) if direct else url
            headers = {name: value for name, value in self.headers.items() if name.lower() not in HOP_HEADERS}
            # HTTP forward proxies receive an absolute request target while the
            # Host header continues to identify the requested website.
            headers["Host"] = parsed.netloc
            connection = http.client.HTTPConnection(host, port, timeout=60)
            try:
                connection.request(self.command, target, body=body, headers=headers)
                response = connection.getresponse()
                self.send_response(response.status, response.reason)
                for name, value in response.getheaders():
                    if name.lower() not in HOP_HEADERS and name.lower() != "content-length":
                        self.send_header(name, value)
                self.send_header("Connection", "close")
                self.end_headers()
                if self.command != "HEAD":
                    while chunk := response.read(16384):
                        self.wfile.write(chunk)
            finally:
                connection.close()
        except (OSError, ValueError, http.client.HTTPException) as error:
            self.send_error(502, str(error))
        self.close_connection = True

    def log_message(self, fmt, *args):
        print("retromodem-online-proxy:", fmt % args, flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer((os.environ.get("RETROMODEM_PROXY_HOST", "0.0.0.0"), 8080), Handler).serve_forever()
