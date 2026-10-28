#!/usr/bin/python3
"""HTTP/1.0 friendly web simplifier for RetroModem's legacy clients.

The processing model is derived from RetroWEB: fetch modern HTTPS on behalf of
the client, keep the useful document body, rewrite links to plain HTTP, and
optionally turn images into small GIFs.  This is deliberately a forward proxy,
so the original site URL remains visible in the browser.
"""

from __future__ import annotations

import html
import os
import re
import concurrent.futures
import http.client
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bs4 import BeautifulSoup
try:
    import local_ui
except ModuleNotFoundError:
    from web import local_ui

CONFIG = "/etc/retromodem/retromodem.env"
MAX_DOCUMENT = 8 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (compatible; RetroModem RetroWEB Proxy/1.0)"
LOCAL_HOSTS = {"search.retromodem", "192.168.77.1", "127.0.0.1", "localhost", "retromodem.local"}
NON_DOCUMENT_SUFFIXES = {
    ".bmp", ".css", ".gif", ".ico", ".jpeg", ".jpg", ".js", ".pdf",
    ".png", ".svg", ".tif", ".tiff", ".webp", ".zip",
}


def settings() -> dict[str, str]:
    result = dict(os.environ)
    try:
        with open(CONFIG, encoding="utf-8") as source:
            for raw in source:
                raw = raw.strip()
                if raw and not raw.startswith("#") and "=" in raw:
                    key, value = raw.split("=", 1)
                    result[key] = value.strip().strip("'\"")
    except OSError:
        pass
    return result


def requested_url(handler: BaseHTTPRequestHandler) -> str:
    value = handler.path
    if not value.startswith(("http://", "https://")):
        value = "http://" + handler.headers.get("Host", "") + value
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("invalid URL")
    return value


def upstream_url(url: str, excluded: bool) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme == "http" and not excluded:
        parsed = parsed._replace(scheme="https")
    return urllib.parse.urlunsplit(parsed)


def browser_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(parsed._replace(scheme="http"))


def is_excluded(host: str, values: dict[str, str]) -> bool:
    domains = re.split(r"[\s,]+", values.get("RETROMODEM_PROXY_EXCEPTIONS", values.get("RETROMODEM_68KPROXY_EXCEPTIONS", "")))
    host = host.lower().rstrip(".")
    return any(host == item or host.endswith("." + item) for item in domains if item)


def fetch(url: str, limit: int) -> tuple[bytes, str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=20) as response:
        content_type = response.headers.get_content_type()
        final_url = response.geturl()
        length = response.headers.get("Content-Length")
        if length and int(length) > limit:
            raise ValueError("response too large")
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("response too large")
        return data, content_type, final_url


_cache = {}
_pending = {}
_cache_lock = threading.Lock()


def fetch_retroweb(url: str, values: dict[str, str]) -> tuple[bytes, str]:
    key = (url, values.get('RETROMODEM_PROXY_IMAGE_MODE', 'inline'),
           values.get('RETROMODEM_PROXY_IMAGE_WIDTH', ''), values.get('RETROMODEM_PROXY_IMAGE_HEIGHT', ''))
    with _cache_lock:
        cached = _cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        future = _pending.get(key)
        owner = future is None
        if owner:
            future = concurrent.futures.Future()
            _pending[key] = future
    if not owner:
        return future.result(timeout=60)
    try:
        result = _fetch_retroweb(url, values)
        with _cache_lock:
            # Bound total memory as well as entry count on the Pi.
            while _cache and (len(_cache) >= 32 or sum(len(v[1][0]) for v in _cache.values()) + len(result[0]) > 16 * 1024 * 1024):
                del _cache[next(iter(_cache))]
            ttl = 15 if b'<title>Website niet beschikbaar</title>' in result[0] else 60
            _cache[key] = (time.monotonic() + ttl, result)
        future.set_result(result)
        return result
    except Exception as error:
        future.set_exception(error)
        raise
    finally:
        with _cache_lock:
            _pending.pop(key, None)


def _fetch_retroweb(url: str, values: dict[str, str]) -> tuple[bytes, str]:
    mode = values.get("RETROMODEM_PROXY_IMAGE_MODE", "inline")
    endpoint = "http://127.0.0.1:8090/proxy.php?" + urllib.parse.urlencode({"url": url, "img": mode})
    request = urllib.request.Request(endpoint, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        data = response.read(MAX_DOCUMENT + 1)
        if len(data) > MAX_DOCUMENT:
            raise ValueError("processed response too large")
    if content_type.startswith("text/html"):
        text = data.decode("iso-8859-1", "replace")
        text = re.sub(r'<p>\s*<a href="http://127\.0\.0\.1:8090/index\.php.*?</p>\s*<hr>\s*', '', text, count=1, flags=re.S)
        pattern = re.compile(r'http://127\.0\.0\.1:8090/(?:proxy\.php|image_cruncher\.php)\?url=([^"\' <]+)')
        def original_link(match: re.Match[str]) -> str:
            encoded = re.split(r'(?:&|&amp;)img=', match.group(1), maxsplit=1)[0]
            return browser_url(urllib.parse.unquote(html.unescape(encoded)))
        text = pattern.sub(original_link, text)
        data = text.encode("iso-8859-1", "replace")
    return data, content_type


def likely_document(url: str) -> bool:
    path = urllib.parse.urlsplit(url).path.lower()
    return not any(path.endswith(suffix) for suffix in NON_DOCUMENT_SUFFIXES)


def search_page(query: str = "", language: str | None = None) -> bytes:
    language = language or local_ui.language()
    t = lambda nl, en: local_ui.tr(language, nl, en)
    items = ""
    if query:
        if re.match(r"^(?:https?://)?[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:/|$)", query):
            target = query if query.startswith(("http://", "https://")) else "http://" + query
            items = '<p><a href="%s">Open %s</a></p>' % (html.escape(browser_url(target), quote=True), html.escape(query))
        else:
            try:
                url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
                request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Accept": "text/html", "Referer": "https://duckduckgo.com/"})
                with urllib.request.urlopen(request, timeout=20) as response:
                    data = response.read(2 * 1024 * 1024)
                soup = BeautifulSoup(data, "html.parser")
                rows = []
                links = soup.select("a.result__a, a.result-link")
                if not links:
                    fallback = "https://www.startpage.com/sp/search?" + urllib.parse.urlencode({"query": query, "language": "english"})
                    request = urllib.request.Request(fallback, headers={"User-Agent": "Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Accept": "text/html"})
                    with urllib.request.urlopen(request, timeout=20) as response:
                        soup = BeautifulSoup(response.read(2 * 1024 * 1024), "html.parser")
                    links = soup.select("a.result-link, a.w-gl__result-title, a[href*='/sp/click']")
                for link in links[:20]:
                    href = link.get("href", "")
                    parsed = urllib.parse.urlsplit(href)
                    redirect = urllib.parse.parse_qs(parsed.query).get("uddg", [])
                    if redirect:
                        href = redirect[0]
                    if href.startswith(("http://", "https://")):
                        rows.append('<li><a href="%s">%s</a></li>' % (html.escape(browser_url(href), quote=True), html.escape(link.get_text(" ", strip=True))))
                items = '<h2>' + t('Zoekresultaten', 'Search results') + '</h2><ol>' + ''.join(rows) + '</ol>' if rows else '<p>' + t('Geen resultaten gevonden.', 'No results found.') + '</p>'
            except (OSError, ValueError, urllib.error.URLError):
                items = '<p>' + t('Zoeken is tijdelijk niet beschikbaar.', 'Search is temporarily unavailable.') + '</p>'
    title = t('RetroWEB zoeken', 'RetroWEB search')
    page = ('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 2.0//EN"><html><head><title>' + title + '</title></head><body>'
            '<h1>' + title + '</h1><p>' + t('Zoek het web of voer een webadres in.', 'Search the web or enter a web address.') + '</p>'
            '<form method="get" action="/"><input type="text" name="q" size="40" value="%s"> '
            '<input type="submit" value="' + t('Zoeken / Openen', 'Search / Open') + '"></form>%s<hr><p>' + t('Gebaseerd op ', 'Based on ') +
            '<a href="http://retroweb.bjrno.com">RetroWEB</a> | <a href="http://chatgpt.retromodem/">ChatGPT</a></p></body></html>') % (html.escape(query, quote=True), items)
    return page.encode("iso-8859-1", "xmlcharrefreplace")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "RetroModem-RetroWEB/1.0"

    def do_CONNECT(self) -> None:
        self.send_error(501, "Use an http:// URL; the proxy fetches HTTPS upstream")

    def relay_chat(self, original: str) -> None:
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 <= length <= 16000:
            self.send_error(413)
            return
        connection = http.client.HTTPConnection('127.0.0.1', 80, timeout=200)
        try:
            parsed = urllib.parse.urlsplit(original)
            target = urllib.parse.urlunsplit(('', '', parsed.path or '/', parsed.query, ''))
            connection.request(self.command, target,
                               body=self.rfile.read(length) if length else None,
                               headers={'Host': 'chatgpt.retromodem', 'Content-Type': 'application/x-www-form-urlencoded'})
            response = connection.getresponse()
            self.send_response(response.status)
            self.send_header('Content-Type', 'text/html; charset=iso-8859-1')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True
            while True:
                data = response.read1(4096)
                if not data:
                    break
                self.wfile.write(data)
                self.wfile.flush()
        finally:
            connection.close()

    def do_POST(self) -> None:
        original = requested_url(self)
        if urllib.parse.urlsplit(original).hostname == 'chatgpt.retromodem':
            self.relay_chat(original)
        else:
            self.send_error(405, 'POST is alleen beschikbaar voor ChatGPT')

    def do_GET(self) -> None:
        try:
            values = settings()
            original = requested_url(self)
            parsed = urllib.parse.urlsplit(original)
            host = parsed.hostname or ""
            if host == 'chatgpt.retromodem':
                self.relay_chat(original)
                return
            if host in LOCAL_HOSTS and (parsed.port in {None, 8080}):
                query = urllib.parse.parse_qs(parsed.query).get("q", [""])[0].strip()[:500]
                self.reply(search_page(query), "text/html; charset=iso-8859-1")
                return
            excluded = is_excluded(host, values)
            if excluded:
                data, content_type, _ = fetch(original, MAX_DOCUMENT)
                self.reply(data, content_type)
            elif likely_document(original):
                self.reply_retroweb_live(upstream_url(original, False), values)
            else:
                data, content_type = fetch_retroweb(upstream_url(original, False), values)
                self.reply(data, content_type)
        except (urllib.error.URLError, ValueError, OSError) as error:
            message = ("<html><body><h1>Pagina niet beschikbaar</h1><p>" + html.escape(str(error)) + "</p></body></html>").encode("iso-8859-1", "replace")
            self.reply(message, "text/html; charset=iso-8859-1", 502)

    def reply_retroweb_live(self, url: str, values: dict[str, str]) -> None:
        """Acknowledge slow page extraction immediately and keep old clients alive."""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=iso-8859-1")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(b"<!-- RetroModem verwerkt de pagina -->\r\n")
        self.wfile.flush()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fetch_retroweb, url, values)
            while True:
                try:
                    data, _ = future.result(timeout=1)
                    self.wfile.write(data)
                    return
                except concurrent.futures.TimeoutError:
                    self.wfile.write(b" ")
                    self.wfile.flush()
                except (OSError, ValueError, urllib.error.URLError) as error:
                    self.wfile.write(('<h1>Pagina niet beschikbaar</h1><p>' + html.escape(str(error)) + '</p>').encode('iso-8859-1', 'replace'))
                    return

    def reply(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, pattern: str, *args: object) -> None:
        print("%s - %s" % (self.client_address[0], pattern % args), flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
