#!/usr/bin/python3
"""HTTP/1.0 friendly web simplifier for RetroModem's legacy clients.

The processing model is derived from RetroWEB: fetch modern HTTPS on behalf of
the client, keep the useful document body, rewrite links to plain HTTP, and
optionally turn images into small GIFs.  This is deliberately a forward proxy,
so the original site URL remains visible in the browser.
"""

from __future__ import annotations

import html
import ipaddress
import json
import os
from pathlib import Path
import re
import concurrent.futures
import http.client
import threading
import tempfile
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
PAGINATION_PATH = '/__retroweb/page'
IMAGE_PATH = '/__retroweb/image'
IMAGE_CHOICE_FILE = Path('/var/lib/retromodem/proxy-image-choice.json')
_image_session_lock = threading.Lock()
_image_sessions = {}


def image_client(handler: BaseHTTPRequestHandler) -> str:
    peer = getattr(handler, 'client_address', ('127.0.0.1', 0))[0]
    # Only our loopback web relay may supply the original client address.
    forwarded = handler.headers.get('X-Retromodem-Client', '') if peer in {'127.0.0.1', '::1'} else ''
    try:
        return str(ipaddress.ip_address(forwarded or peer))
    except ValueError:
        return peer


def image_session_key(client: str) -> tuple[str, str]:
    if client == '192.168.77.2':
        try:
            marker = Path('/sys/class/net/ppp0/ifindex').read_text().strip()
        except OSError:
            marker = 'disconnected'
        return client, marker
    return client, 'process-session'


def remembered_image_mode() -> str:
    try:
        if IMAGE_CHOICE_FILE.is_symlink() or IMAGE_CHOICE_FILE.stat().st_size > 256:
            return 'inline'
        value = json.loads(IMAGE_CHOICE_FILE.read_text())
        if isinstance(value, dict) and set(value) == {'mode'} and value['mode'] in {'inline', 'links'}:
            return value['mode']
    except (OSError, ValueError, TypeError):
        pass
    return 'inline'


def remember_image_mode(mode: str) -> None:
    if IMAGE_CHOICE_FILE.is_symlink() or IMAGE_CHOICE_FILE.parent.is_symlink():
        raise OSError('Image preference path must not be a symlink')
    IMAGE_CHOICE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.proxy-image-choice-', dir=IMAGE_CHOICE_FILE.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps({'mode': mode}) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, IMAGE_CHOICE_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def session_image_mode(values: dict[str, str], client: str, explicit: str | None = None) -> str:
    policy = values.get('RETROMODEM_PROXY_IMAGE_START', values.get('RETROMODEM_PROXY_IMAGE_MODE', 'inline'))
    if policy not in {'inline', 'links', 'remember'}:
        policy = 'inline'
    if explicit is not None and explicit not in {'inline', 'links'}:
        raise ValueError('Invalid image mode')
    key = image_session_key(client)
    with _image_session_lock:
        if key not in _image_sessions:
            # Forget the prior connection for this client; do not inherit a
            # toggle when fixed start mode is requested on PPP reconnect.
            for previous in list(_image_sessions):
                if previous[0] == client:
                    del _image_sessions[previous]
            while len(_image_sessions) >= 128:
                del _image_sessions[next(iter(_image_sessions))]
            _image_sessions[key] = remembered_image_mode() if policy == 'remember' else policy
        if explicit is not None:
            _image_sessions[key] = explicit
            # Record the actual last PPP choice regardless of the start policy.
            # A later switch to "remember" must inherit that choice, while a
            # fixed start mode still wins when the next PPP session begins.
            # Local QA/relay requests without a real forwarded peer never write.
            if client == '192.168.77.2' and remembered_image_mode() != explicit:
                try:
                    remember_image_mode(explicit)
                except OSError:
                    print('RetroModem: could not persist image preference', flush=True)
        return _image_sessions[key]


def pagination_parameters(query: str) -> dict[str, str]:
    values = urllib.parse.parse_qs(query, keep_blank_values=True)
    if not {'document', 'part'} <= set(values) or not set(values) <= {'document', 'part', 'img', 'block'} or any(len(items) != 1 for items in values.values()):
        raise ValueError('Invalid page reference')
    token, part = values['document'][0], values['part'][0]
    if not re.fullmatch(r'[a-f0-9]{64}', token) or not re.fullmatch(r'(?:[1-9][0-9]{0,5}|all)', part):
        raise ValueError('Invalid page reference')
    result = {'document': token, 'part': part}
    if 'img' in values:
        mode = values['img'][0]
        if mode not in {'inline', 'links'}:
            raise ValueError('Invalid image mode')
        result['img'] = mode
    if 'block' in values:
        block = values['block'][0]
        if not re.fullmatch(r'b[1-9][0-9]{0,5}', block):
            raise ValueError('Invalid document block')
        result['block'] = block
    return result


def image_parameters(query: str) -> dict[str, str]:
    values = urllib.parse.parse_qs(query, keep_blank_values=True)
    if 'url' not in values or not set(values) <= {'url', 'w', 'h'} or any(len(items) != 1 for items in values.values()):
        raise ValueError('Invalid image reference')
    url = values['url'][0]
    if len(url) > 2048 or any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise ValueError('Invalid image URL')
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError('Invalid image URL')
    result = {'url': url}
    for key in ('w', 'h'):
        if key in values:
            dimension = values[key][0]
            if not re.fullmatch(r'[1-9][0-9]{0,3}', dimension) or not 1 <= int(dimension) <= 4096:
                raise ValueError('Invalid image dimensions')
            result[key] = dimension
    return result


def rewrite_retroweb_html(data: bytes) -> bytes:
    text = data.decode('iso-8859-1', 'replace')
    pattern = re.compile(r'http://127\.0\.0\.1:8090/(?:proxy\.php|image_cruncher\.php)\?[^"\' <>]+')

    def browser_link(match: re.Match[str]) -> str:
        address = urllib.parse.urlsplit(html.unescape(match.group(0)))
        query = urllib.parse.parse_qs(address.query, keep_blank_values=True)
        if address.path == '/image_cruncher.php':
            try:
                params = image_parameters(address.query)
            except ValueError:
                return '#invalid-image-reference'
            result = 'http://search.retromodem' + IMAGE_PATH + '?' + urllib.parse.urlencode(params)
        elif 'document' in query:
            try:
                params = pagination_parameters(address.query)
            except ValueError:
                return '#invalid-page-reference'
            result = 'http://search.retromodem' + PAGINATION_PATH + '?' + urllib.parse.urlencode(params)
            if address.fragment:
                result += '#' + address.fragment
        elif len(query.get('url', [])) == 1:
            result = browser_url(query['url'][0])
        else:
            return match.group(0)
        return html.escape(result, quote=True)

    return pattern.sub(browser_link, text).encode('iso-8859-1', 'replace')


def fetch_retroweb_part(params: dict[str, str]) -> tuple[bytes, str]:
    # The UI language is a server setting, never a browser parameter.
    # Inject current values even for an older document/snapshot link.
    query = dict(params)
    query.update(rendering_options())
    endpoint = 'http://127.0.0.1:8090/proxy.php?' + urllib.parse.urlencode(query)
    with urllib.request.urlopen(endpoint, timeout=30) as response:
        data = response.read(MAX_DOCUMENT + 1)
        if len(data) > MAX_DOCUMENT:
            raise ValueError('processed response too large')
        content_type = response.headers.get('Content-Type', 'text/html; charset=iso-8859-1')
    return rewrite_retroweb_html(data), content_type


def fetch_retroweb_image(params: dict[str, str]) -> tuple[bytes, str]:
    # The core applies its existing URL/SSRF checks and returns the converted
    # image directly. Never rediscover its type through proxy.php: that loses
    # the display dimensions and adds an unnecessary second upstream request.
    endpoint = 'http://127.0.0.1:8090/image_cruncher.php?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(endpoint, timeout=45) as response:
        data = response.read(MAX_DOCUMENT + 1)
        if len(data) > MAX_DOCUMENT:
            raise ValueError('processed image too large')
        content_type = response.headers.get('Content-Type', 'image/gif')
    return data, content_type


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


def rendering_options() -> dict[str, str]:
    language = 'en' if local_ui.language() == 'en' else 'nl'
    return {'lang': language}


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
    options = rendering_options()
    key = (url, values.get('RETROMODEM_PROXY_IMAGE_MODE', 'inline'),
           values.get('RETROMODEM_PROXY_IMAGE_WIDTH', ''), values.get('RETROMODEM_PROXY_IMAGE_HEIGHT', ''),
           values.get('RETROMODEM_PROXY_PAGE_SIZE', '18000'), values.get('RETROMODEM_PROXY_PAGE_IMAGES', '5'),
           options['lang'])
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
    page_size = values.get('RETROMODEM_PROXY_PAGE_SIZE', '18000')
    page_images = values.get('RETROMODEM_PROXY_PAGE_IMAGES', '5')
    if page_size not in {'0', '12000', '18000', '25000', '50000', '75000', '100000', '125000', '150000', '175000', '200000', '250000', '500000', '750000', '1000000', '1250000', '1500000', '1750000', '2000000'}:
        page_size = '18000'
    if page_images not in {str(n) for n in range(0, 11)}:
        page_images = '5'
    endpoint = "http://127.0.0.1:8090/proxy.php?" + urllib.parse.urlencode({
        "url": url, "img": mode, "page_size": page_size, "page_images": page_images,
        **rendering_options()})
    request = urllib.request.Request(endpoint, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        data = response.read(MAX_DOCUMENT + 1)
        if len(data) > MAX_DOCUMENT:
            raise ValueError("processed response too large")
    if content_type.startswith("text/html"):
        data = rewrite_retroweb_html(data)
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
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
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
            client = image_client(self)
            values['RETROMODEM_PROXY_IMAGE_MODE'] = session_image_mode(values, client)
            original = requested_url(self)
            parsed = urllib.parse.urlsplit(original)
            host = parsed.hostname or ""
            if host == 'chatgpt.retromodem':
                self.relay_chat(original)
                return
            if host in LOCAL_HOSTS and (parsed.port in {None, 8080}):
                if parsed.path == IMAGE_PATH:
                    try:
                        params = image_parameters(parsed.query)
                    except ValueError:
                        self.send_error(400, 'Invalid image reference')
                        return
                    try:
                        data, content_type = fetch_retroweb_image(params)
                        self.reply(data, content_type)
                    except urllib.error.HTTPError as error:
                        status = error.code if error.code in {400, 403, 404, 410, 413} else 502
                        self.send_error(status, 'Image unavailable')
                    return
                if parsed.path == PAGINATION_PATH:
                    try:
                        params = pagination_parameters(parsed.query)
                    except ValueError:
                        self.send_error(400, 'Invalid page reference')
                        return
                    try:
                        data, content_type = fetch_retroweb_part(params)
                        if 'img' in params:
                            session_image_mode(values, client, params['img'])
                        self.reply(data, content_type)
                    except urllib.error.HTTPError as error:
                        status = error.code if error.code in {400, 404, 410} else 502
                        self.reply(b'<html><body><h1>Page unavailable</h1><p>This page reference is invalid or expired. Open the original page again.</p></body></html>',
                                   'text/html; charset=iso-8859-1', status)
                    return
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


class RetroWebHTTPServer(ThreadingHTTPServer):
    # Old browsers open image connections in bursts over a slow IrDA link.
    # The default queue of five is too small during TCP handshakes/retries.
    request_queue_size = 128
    daemon_threads = True


if __name__ == "__main__":
    RetroWebHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
