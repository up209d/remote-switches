import os

# Root directory on the Pico that holds the built web app (web/dist -> www/).
WEB_ROOT = "www"
CHUNK = 512

MIME = {
    "html": "text/html",
    "js": "text/javascript",
    "mjs": "text/javascript",
    "css": "text/css",
    "json": "application/json",
    "svg": "image/svg+xml",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "ico": "image/x-icon",
    "webp": "image/webp",
    "woff": "font/woff",
    "woff2": "font/woff2",
    "ttf": "font/ttf",
    "txt": "text/plain",
    "map": "application/json",
}


def _stat(path):
    try:
        return os.stat(path)
    except OSError:
        return None


def _is_file(st):
    # st[0] is st_mode; 0x8000 flags a regular file
    return st is not None and (st[0] & 0x8000) != 0


def content_type(path):
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return MIME.get(ext, "application/octet-stream")


def _resolve(url_path):
    """Map a URL path to a file on disk, with SPA fallback to index.html."""
    if not url_path or url_path == "/":
        return WEB_ROOT + "/index.html"

    # Strip query string and leading slash, block traversal
    clean = url_path.split("?", 1)[0].lstrip("/")
    if ".." in clean:
        return None

    candidate = WEB_ROOT + "/" + clean
    if _is_file(_stat(candidate)):
        return candidate

    # SPA fallback: unknown routes serve index.html
    return WEB_ROOT + "/index.html"


def write_all(conn, data):
    """
    Send every byte of `data`. MicroPython's socket.send() may do a "short
    write" (send fewer bytes than given and return that count), so we loop
    until the whole buffer is transmitted — otherwise large responses get
    truncated and the browser reports ERR_CONTENT_LENGTH_MISMATCH.
    """
    if isinstance(data, str):
        data = data.encode()
    mv = memoryview(data)
    total = 0
    length = len(data)
    while total < length:
        sent = conn.send(mv[total:])
        if sent:
            total += sent
    return length


def serve(conn, url_path, gzip_ok=False):
    """Serve a static file (or SPA fallback). Returns True if something was sent."""
    path = _resolve(url_path)
    st = _stat(path) if path else None

    # Explicit None checks (not just _is_file) so both `path` and `st` narrow
    # to non-None for the type checker in the success path below.
    if path is None or st is None or not _is_file(st):
        body = b"404 Not Found"
        write_all(conn, (
            "HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\n"
            "Content-Length: %d\r\nConnection: close\r\n\r\n" % len(body)
        ))
        write_all(conn, body)
        return True

    # Content-Type comes from the *logical* path; if the client accepts gzip
    # and a pre-compressed twin exists, stream that instead.
    ctype = content_type(path)
    open_path = path
    encoding = ""
    if gzip_ok:
        gz = path + ".gz"
        gz_st = _stat(gz)
        if _is_file(gz_st):
            open_path = gz
            st = gz_st
            encoding = "Content-Encoding: gzip\r\n"

    size = st[6]
    headers = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: %s\r\n"
        "Content-Length: %d\r\n"
        "%s"
        "Vary: Accept-Encoding\r\n"
        "Cache-Control: no-cache\r\n"
        "Connection: close\r\n\r\n" % (ctype, size, encoding)
    )
    write_all(conn, headers)

    with open(open_path, "rb") as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            write_all(conn, chunk)
    return True
