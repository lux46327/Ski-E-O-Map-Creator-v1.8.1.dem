"""HTTP downloads with an identifying User-Agent, retries, per-host connection limits and cancellation."""
import http.client
import logging
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import VERSION

log = logging.getLogger(__name__)
USER_AGENT = 'SkiEO-Map-Creator/%s (community mod tool for the game Ski-E-O!; Windows)' % VERSION
_host_slots = {}
_host_lock = threading.Lock()


class Cancelled(Exception):
    pass


class NetError(Exception):
    pass


class CancelToken:
    def __init__(self):
        self._ev = threading.Event()

    def cancel(self):
        self._ev.set()

    @property
    def cancelled(self):
        return self._ev.is_set()

    def check(self):
        if self._ev.is_set():
            raise Cancelled()

    def sleep(self, seconds):
        if self._ev.wait(seconds):
            raise Cancelled()


NEVER = CancelToken()


def _slot(host, limit):
    with _host_lock:
        s = _host_slots.get(host)
        if s is None:
            s = _host_slots[host] = threading.BoundedSemaphore(limit)
        return s


class _HTTPStatus(Exception):
    def __init__(self, code, reason):
        super().__init__('%d %s' % (code, reason))
        self.code, self.reason = code, reason


_pools = {}
_pool_lock = threading.Lock()
def _ssl_context():
    """TLS verification through the operating system's own certificate check (truststore), as browsers do: it also
    accepts servers that send an incomplete certificate chain, which Windows completes (the likely cause of
    the certificate error from IGN Spain's servicios.idee.es). Without truststore, Python's default check is used."""
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return ssl.create_default_context()


_ssl = _ssl_context()


def _pooled(parts, headers, timeout, cancel):
    """GET over a kept-alive HTTPS connection (map tiles: one TLS handshake per server instead of per tile)"""
    host = parts.hostname
    with _pool_lock:
        pool = _pools.setdefault(host, [])
        conn = pool.pop() if pool else None
    if conn is None:
        conn = http.client.HTTPSConnection(host, parts.port or 443, timeout=timeout, context=_ssl)
    path = (parts.path or '/') + ('?' + parts.query if parts.query else '')
    try:
        try:
            conn.request('GET', path, headers=headers)
            r = conn.getresponse()
        except (http.client.RemoteDisconnected, ConnectionResetError, ConnectionAbortedError, BrokenPipeError,
                http.client.CannotSendRequest):
            conn.close()                                           # the server dropped the idle connection
            conn = http.client.HTTPSConnection(host, parts.port or 443, timeout=timeout, context=_ssl)
            conn.request('GET', path, headers=headers)
            r = conn.getresponse()
        ok = 206 if 'Range' in headers else 200
        if r.status in (200, 206) and r.status != ok:      # the whole file where a part was asked for: don't read it
            raise _HTTPStatus(r.status, 'instead of %d' % ok)
        chunks = []
        while True:
            cancel.check()
            b = r.read(1 << 16)
            if not b:
                break
            chunks.append(b)
        if r.status != ok:
            raise _HTTPStatus(r.status, r.reason)
        if r.will_close:
            conn.close()
        else:
            with _pool_lock:
                _pools[host].append(conn)
            conn = None
        return b''.join(chunks)
    finally:
        if conn is not None:
            conn.close()


_req_session = None
_req_lock = threading.Lock()


def _requests_get(url, headers, timeout, cancel):
    """Second TLS route for servers whose certificate chain http.client's check rejects although the system trusts it
    (observed with the Polish and Slovak geoportals): the same verification, done through requests/urllib3 with the
    operating system's trust store. Verification stays on; a really invalid certificate fails here too."""
    global _req_session
    import requests
    from requests.adapters import HTTPAdapter
    with _req_lock:
        if _req_session is None:
            class _Adapter(HTTPAdapter):
                def init_poolmanager(self, *a, **k):
                    k['ssl_context'] = _ssl_context()
                    super().init_poolmanager(*a, **k)

            _req_session = requests.Session()
            _req_session.mount('https://', _Adapter())
    r = _req_session.get(url, headers=headers, timeout=timeout, stream=True)
    try:
        chunks = []
        for b in r.iter_content(1 << 16):
            cancel.check()
            chunks.append(b)
        if r.status_code != (206 if 'Range' in headers else 200):
            raise _HTTPStatus(r.status_code, r.reason)
        return b''.join(chunks)
    finally:
        r.close()


def _is_cert_error(e):
    return isinstance(e, ssl.SSLCertVerificationError) or isinstance(getattr(e, 'reason', None), ssl.SSLCertVerificationError)


def get(url, timeout=60, retries=4, cancel=NEVER, accept=None, per_host=4, not_found_ok=False, byte_range=None):
    """GET url -> bytes. 404 returns None when not_found_ok. byte_range=(first, last): only those bytes (206).
    Raises NetError with a readable message."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ''
    headers = {'User-Agent': USER_AGENT, 'Accept': accept or '*/*', 'Accept-Encoding': 'identity'}
    if byte_range:
        headers['Range'] = 'bytes=%d-%d' % tuple(byte_range)
    direct = parts.scheme == 'https' and not urllib.request.getproxies()
    last = None
    for attempt in range(retries + 1):
        cancel.check()
        try:
            with _slot(host, per_host):
                cancel.check()                    # may have waited for the slot a while
                if direct:
                    return _pooled(parts, headers, timeout, cancel)
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                    if byte_range and r.status != 206:
                        raise _HTTPStatus(r.status, 'instead of 206')
                    chunks = []
                    while True:
                        cancel.check()
                        b = r.read(1 << 16)
                        if not b:
                            break
                        chunks.append(b)
                    return b''.join(chunks)
        except Cancelled:
            raise
        except (urllib.error.HTTPError, _HTTPStatus) as e:
            if e.code == 404 and not_found_ok:
                return None
            last = 'the server answered %d %s' % (e.code, e.reason)
            if e.code in (200, 206, 400, 401, 403, 404, 410):
                break
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError, http.client.HTTPException) as e:
            last = str(getattr(e, 'reason', e) or type(e).__name__)
            if parts.scheme == 'https' and _is_cert_error(e):
                try:                                          # second TLS route (see _requests_get); same verification
                    return _requests_get(url, headers, timeout, cancel)
                except Cancelled:
                    raise
                except _HTTPStatus as e2:
                    if e2.code == 404 and not_found_ok:
                        return None
                    last = 'the server answered %d %s' % (e2.code, e2.reason)
                    if e2.code in (400, 401, 403, 404, 410):
                        break
                except Exception as e2:
                    last = str(e2)[:200]
        log.warning('download failed (%s), attempt %d: %s', host, attempt + 1, last)
        if attempt < retries:
            cancel.sleep(min(2 ** attempt, 20))
    raise NetError('Could not download from %s (%s). Check your internet connection and try again.' % (host, last))


class RateLimit:
    """At most one call per `interval` seconds (Nominatim's usage policy asks for 1 request per second)."""

    def __init__(self, interval):
        self.interval = interval
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.monotonic()
            if now < self._next:
                time.sleep(self._next - now)
            self._next = max(now, self._next) + self.interval
