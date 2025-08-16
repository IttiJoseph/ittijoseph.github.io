#!/usr/bin/env python3
# mirror_framer.py
#
# Place in: C:\Users\Itti\ittijoseph.github.io\mirror_framer.py
# Usage:
#   py -3 mirror_framer.py --html index.html
# Optional:
#   --only-framer-hosts   (skip non-Framer CDNs)
#
import argparse
import os
import re
import sys
import hashlib
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

try:
    import cssutils
    CSSUTILS_AVAILABLE = True
    cssutils.log.setLevel("FATAL")
except Exception:
    CSSUTILS_AVAILABLE = False

# ---------- Your local layout ----------
ROOT = Path(".").resolve()
DIR_CSS   = ROOT / "assets" / "css"
DIR_JS    = ROOT / "assets" / "js"
DIR_JS_FR = ROOT / "assets" / "js" / "framer"
DIR_IMG   = ROOT / "assets" / "images"
DIR_FONT  = ROOT / "assets" / "fonts"

for d in (DIR_CSS, DIR_JS, DIR_JS_FR, DIR_IMG, DIR_FONT):
    d.mkdir(parents=True, exist_ok=True)

# ---------- HTTP ----------
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; FramerMirror/1.1; +https://github.com/)",
})
TIMEOUT = 30

# ---------- Patterns ----------
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".svg", ".ico", ".bmp")
MEDIA_EXT = (".mp4", ".webm", ".ogg", ".mp3", ".wav")
FONT_EXT = (".woff2", ".woff", ".ttf", ".otf")
CSS_EXT = (".css",)
JS_EXT  = (".js", ".mjs", ".map")
JSON_EXT = (".json",)

ASSET_EXT_ALL = IMG_EXT + MEDIA_EXT + FONT_EXT + CSS_EXT + JS_EXT + JSON_EXT

URL_IN_TEXT_RE = re.compile(
    r"""https?://[^\s'"]+?(?:\.(?:png|jpe?g|webp|avif|gif|svg|ico|bmp|mp4|webm|ogg|mp3|wav|json|css|js|map|woff2?|ttf|otf))""",
    re.IGNORECASE,
)

FRAMER_HOSTS = (
    "framerusercontent.com",
    "framerstatic.com",
    "framer.com",
    "cdn.framer.com",
)

def is_http_url(u: str) -> bool:
    try:
        p = urlparse(u)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False

def host_looks_like_framer(u: str) -> bool:
    try:
        netloc = urlparse(u).netloc.lower()
        return any(h in netloc for h in FRAMER_HOSTS)
    except Exception:
        return False

def ext_of(url: str) -> str:
    p = urlparse(url)
    base = p.path.rsplit("/", 1)[-1]
    dot = base.rfind(".")
    return base[dot:].lower() if dot != -1 else ""

def choose_local_dir(url: str) -> Path:
    e = ext_of(url)
    if e in IMG_EXT or e in MEDIA_EXT:
        return DIR_IMG
    if e in FONT_EXT:
        return DIR_FONT
    if e in CSS_EXT:
        return DIR_CSS
    if e in JS_EXT:
        # heuristically put Framer runtime into js/framer
        if "framer" in url.lower() or urlparse(url).path.lower().endswith((".mjs",)):
            return DIR_JS_FR
        return DIR_JS
    if e in JSON_EXT:
        return DIR_JS  # JSON alongside JS
    return DIR_IMG  # default bucket

def ensure_unique_path(dst_dir: Path, filename: str) -> Path:
    """
    Avoid collisions: if filename exists with different content, add short hash.
    """
    candidate = dst_dir / filename
    if not candidate.exists():
        return candidate
    # If exists, keep it. If you want strict uniqueness, append hash.
    return candidate

def hashed_name_from_url(url: str) -> str:
    """
    Keep original basename if present; otherwise create a stable name from URL.
    """
    p = urlparse(url)
    base = Path(p.path).name or "asset"
    # strip cache-busters like ?v=123
    if "?" in base:
        base = base.split("?")[0]
    if "#" in base:
        base = base.split("#")[0]
    if not base:
        # fallback with hash
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
        base = f"asset-{h}"
    return base

def relativize(p: Path) -> str:
    # Always forward slashes for web
    return p.relative_to(ROOT).as_posix()

def extract_from_srcset(value: str) -> list[str]:
    out = []
    for part in value.split(","):
        u = part.strip().split(" ")[0]
        if u:
            out.append(u)
    return out

def parse_css_for_urls(css_text: str) -> set[str]:
    urls = set()
    if CSSUTILS_AVAILABLE:
        try:
            sheet = cssutils.parseString(css_text)
            for rule in sheet:
                # @import
                if getattr(rule, "type", None) == rule.IMPORT_RULE and getattr(rule, "href", None):
                    urls.add(rule.href)
                # Any url(...) in text
                raw = rule.cssText.decode("utf-8", "ignore") if isinstance(rule.cssText, bytes) else str(rule.cssText)
                for m in re.finditer(r'url\(([^)]+)\)', raw, flags=re.IGNORECASE):
                    u = m.group(1).strip(" '\"")
                    urls.add(u)
        except Exception:
            pass
    # Regex fallback (and also run even if cssutils worked, to be safe)
    for m in re.finditer(r'@import\s+url\(([^)]+)\)', css_text, flags=re.IGNORECASE):
        urls.add(m.group(1).strip(" '\""))
    for m in re.finditer(r'url\(([^)]+)\)', css_text, flags=re.IGNORECASE):
        urls.add(m.group(1).strip(" '\""))
    return {u for u in urls if not u.startswith("data:")}

def absolutize(base_url: str, maybe_url: str) -> str:
    if is_http_url(maybe_url):
        return maybe_url
    return urljoin(base_url or "", maybe_url)

def gather_html_asset_urls(soup: BeautifulSoup) -> set[str]:
    urls = set()
    tag_attr = [
        ("img", "src"), ("img", "srcset"), ("img", "data-src"), ("img", "data-srcset"),
        ("source", "src"), ("source", "srcset"),
        ("video", "src"), ("video", "poster"),
        ("audio", "src"), ("track", "src"),
        ("script", "src"),
        ("link", "href"),
        ("iframe", "src"),
        ("embed", "src"),
        ("object", "data"),
        ("use", "href"), ("use", "xlink:href"),
    ]
    lazy_attrs = ["data-bg", "data-background", "data-background-image", "data-lazy", "data-lazy-src"]

    for tag, attr in tag_attr:
        for el in soup.find_all(tag):
            val = el.get(attr)
            if not val:
                continue
            if attr in ("srcset", "data-srcset"):
                for u in extract_from_srcset(val):
                    urls.add(u)
            else:
                urls.add(val)

    # inline style url(...)
    for el in soup.find_all(style=True):
        st = el.get("style", "")
        for m in re.finditer(r'url\(([^)]+)\)', st, flags=re.IGNORECASE):
            urls.add(m.group(1).strip(" '\""))

    # <style> blocks
    for style in soup.find_all("style"):
        css_text = style.string or ""
        urls.update(parse_css_for_urls(css_text))

    # custom lazy attrs on any tag
    for el in soup.find_all():
        for la in lazy_attrs:
            v = el.get(la)
            if v:
                urls.add(v)

    # filter & keep absolute as-is (Framer usually absolute)
    clean = set()
    for u in urls:
        u = (u or "").strip()
        if not u or u.startswith("data:"):
            continue
        clean.add(u)
    return clean

def download(url: str, only_framer: bool) -> Path | None:
    if only_framer and is_http_url(url) and not host_looks_like_framer(url):
        return None
    if not is_http_url(url):
        return None

    dst_dir = choose_local_dir(url)
    filename = hashed_name_from_url(url)
    # If a file with same name exists but different content, we keep same name (hash baked into Framer names anyway)
    dst = ensure_unique_path(dst_dir, filename)
    if dst.exists():
        return dst

    try:
        resp = SESSION.get(url, stream=True, timeout=TIMEOUT)
        resp.raise_for_status()
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(dst, "wb") as f:
            for chunk in resp.iter_content(65536):
                if chunk:
                    f.write(chunk)
        return dst
    except Exception as e:
        print(f"[WARN] Failed {url} -> {dst}: {e}")
        return None

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")

def write_text(path: Path, text: str):
    path.write_text(text, encoding="utf-8")

def scan_js_for_urls(js_text: str) -> set[str]:
    return set(m.group(0) for m in URL_IN_TEXT_RE.finditer(js_text))

def rewrite_in_text(text: str, mapping: dict[str, str]) -> str:
    # Plain string replace for exact absolute URLs
    for remote, local_rel in sorted(mapping.items(), key=lambda x: -len(x[0])):
        text = text.replace(remote, local_rel)
    return text

def rewrite_css_text(css_text: str, mapping: dict[str, str]) -> str:
    # Replace inside url(...) and @import url(...)
    def repl_url(m):
        raw = m.group(1).strip(" '\"")
        new = mapping.get(raw) or mapping.get(absolutize("", raw)) or raw
        return f"url({new})"
    def repl_import(m):
        raw = m.group(1).strip(" '\"")
        new = mapping.get(raw) or mapping.get(absolutize("", raw)) or raw
        return f"@import url({new})"

    css_text = re.sub(r'url\(([^)]+)\)', repl_url, css_text, flags=re.IGNORECASE)
    css_text = re.sub(r'@import\s+url\(([^)]+)\)', repl_import, css_text, flags=re.IGNORECASE)
    return css_text

def process(args):
    # 1) collect all HTMLs at root (index, About, etc.)
    html_paths = set()
    if args.html:
        html_paths.add(Path(args.html).resolve())
    for p in ROOT.glob("*.html"):
        html_paths.add(p.resolve())

    # 2) parse HTML and collect asset URLs
    all_urls = set()
    for hp in sorted(html_paths):
        soup = BeautifulSoup(read_text(hp), "html.parser")
        all_urls |= gather_html_asset_urls(soup)
    # keep only absolute URLs with known asset extensions
    all_urls = {u for u in all_urls if is_http_url(u) and ext_of(u) in ASSET_EXT_ALL}
    if args.only_framer_hosts:
        all_urls = {u for u in all_urls if host_looks_like_framer(u)}

    # 3) download first wave
    rem_to_loc: dict[str, Path] = {}
    for u in sorted(all_urls):
        p = download(u, args.only_framer_hosts)
        if p:
            rem_to_loc[u] = p

    # 4) CSS pass: fetch nested assets mentioned in downloaded CSS, then rewrite CSS
    css_files = [p for p in rem_to_loc.values() if p.suffix.lower() in CSS_EXT]
    nested = set()
    for css in css_files:
        css_text = read_text(css)
        for u in parse_css_for_urls(css_text):
            absu = u if is_http_url(u) else u  # Framer usually absolute
            if not is_http_url(absu):
                continue
            if ext_of(absu) not in ASSET_EXT_ALL:
                continue
            if args.only_framer_hosts and not host_looks_like_framer(absu):
                continue
            nested.add(absu)
    for u in sorted(nested):
        p = download(u, args.only_framer_hosts)
        if p:
            rem_to_loc[u] = p

    # Now rewrite CSS
    mapping = {remote: relativize(local) for remote, local in rem_to_loc.items()}
    for css in css_files:
        css_text = read_text(css)
        css_text = rewrite_css_text(css_text, mapping)
        write_text(css, css_text)

    # 5) JS pass: scan downloaded JS for more asset URLs, download & rewrite inside JS
    js_files = [p for p in rem_to_loc.values() if p.suffix.lower() in JS_EXT]
    discovered = set()
    for js in js_files:
        js_text = read_text(js)
        for u in scan_js_for_urls(js_text):
            if args.only_framer_hosts and not host_looks_like_framer(u):
                continue
            if ext_of(u) in ASSET_EXT_ALL:
                discovered.add(u)
    for u in sorted(discovered):
        p = download(u, args.only_framer_hosts)
        if p:
            rem_to_loc[u] = p

    # Rewrite JS files
    mapping = {remote: relativize(local) for remote, local in rem_to_loc.items()}
    for js in js_files:
        js_text = read_text(js)
        js_text = rewrite_in_text(js_text, mapping)
        write_text(js, js_text)

    # 6) Finally, rewrite all HTML files
    mapping = {remote: relativize(local) for remote, local in rem_to_loc.items()}
    for hp in sorted(html_paths):
        text = read_text(hp)
        # replace absolute URLs
        text = rewrite_in_text(text, mapping)
        # also try to catch url(...) inside inline <style> blocks
        text = rewrite_css_text(text, mapping)
        write_text(hp, text)

    print(f"Downloaded/linked assets: {len(rem_to_loc)}")
    print("Done. Commit updated HTML/CSS/JS + assets/* to GitHub.")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default="index.html", help="Entry HTML file at project root")
    ap.add_argument("--only-framer-hosts", action="store_true", help="Limit to Framer CDNs")
    args = ap.parse_args()
    process(args)
