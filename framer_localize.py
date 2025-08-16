#!/usr/bin/env python3
"""
framer_localize.py
- Localize framerusercontent.com assets (images + .mjs) and rewrite HTML/CSS to local paths
- Ensure every HTML page includes the required local Framer CSS/JS tags
- Optionally rewrite internal links (/About -> About.html) based on files present

Usage examples:
  python framer_localize.py --recursive --include-css --dry-run
  python framer_localize.py --recursive --include-css
  python framer_localize.py --recursive --include-css --no-download
  python framer_localize.py --recursive --rewrite-links
"""

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("This script needs the 'requests' package. Install with:\n  pip install requests", file=sys.stderr)
    sys.exit(1)

# ---------- config
ASSETS_IMG_DIR = Path("assets/images")
ASSETS_JS_DIR  = Path("assets/js/framer")
FRAMER_CSS_HREF = 'assets/css/framer.css'  # you should keep your Framer CSS here
EVENTS_LOCAL   = 'assets/js/framer/events-script-v2.js'
MAIN_MODULE    = 'assets/js/framer/script_main.Bw_SFk1g.mjs'  # keep filename exactly as downloaded

IMAGE_EXT_RE     = r"(?:png|jpe?g|webp|gif|svg|ico|avif)"
FRAMER_HOST_RE   = r"https?://[^\"'\s]*framerusercontent\.com[^\"'\s]*"
FRAMER_IMG_PATH  = re.compile(rf"(?i){FRAMER_HOST_RE}\.({IMAGE_EXT_RE})(?:\?[^\"'\s]*)?")
FRAMER_IMG_QFMT  = re.compile(rf"(?i){FRAMER_HOST_RE}\?(?=[^\"'\s]*\bformat=({IMAGE_EXT_RE}))[^\"'\s]*")
FRAMER_MJS_RE    = re.compile(rf"(?i){FRAMER_HOST_RE}\.mjs(?:\?[^\"'\s]*)?")
EVENTS_SCRIPT_RE = re.compile(r"(?i)https?://events\.framer\.com/script[^\s\"']*")
CSS_URL_RE       = re.compile(r'''url\((['"]?)(?P<u>[^'")]+)\1\)''', re.I)

# ---------- helpers
def short_hash(s: str, n: int = 6) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:n]

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def filename_from_url(url: str, prefer_ext: str = "") -> str:
    """Derive a sane local filename from a URL; add short hash if query exists."""
    u = urlparse(url)
    base = os.path.basename(u.path) or "file"
    name, ext = os.path.splitext(base)
    if not ext and prefer_ext:
        ext = prefer_ext if prefer_ext.startswith(".") else "." + prefer_ext
    if u.query:
        base = f"{name}.{short_hash(url)}{ext}"
    else:
        base = f"{name}{ext}"
    return base

def is_framer(url: str) -> bool:
    return "framerusercontent.com" in url.lower()

def looks_image(url: str) -> bool:
    if re.search(rf"\.({IMAGE_EXT_RE})\b", url, flags=re.I):
        return True
    return bool(re.search(rf"(?i)[?&]format=({IMAGE_EXT_RE})", url))

def preferred_ext(url: str) -> str:
    m = re.search(rf"\.({IMAGE_EXT_RE})\b", url, flags=re.I)
    if m: return "." + m.group(1).lower()
    q = re.search(rf"(?i)[?&]format=({IMAGE_EXT_RE})", url)
    return "." + q.group(1).lower() if q else ""

def download(url: str, dest: Path, dry: bool) -> bool:
    if dest.exists(): return True
    if dry:
        print(f"  DRYRUN: would download -> {dest}")
        return True
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        dest.write_bytes(r.content)
        print(f"  OK: {url} -> {dest}")
        return True
    except Exception as e:
        print(f"  ERROR: download failed {url}  ({e})")
        return False

def replace_all(text: str, mapping: dict) -> str:
    for old, new in mapping.items():
        text = text.replace(old, new)
    return text

def collect_img_urls_from_text(text: str) -> set[str]:
    urls = set()
    urls.update(m.group(0) for m in FRAMER_IMG_PATH.finditer(text))
    urls.update(m.group(0) for m in FRAMER_IMG_QFMT.finditer(text))
    # inline CSS url(...)
    for m in CSS_URL_RE.finditer(text):
        u = m.group("u")
        if is_framer(u) and looks_image(u):
            urls.add(u)
    return urls

# ---------- core processors
def process_file(path: Path, args, link_map: dict[str,str]) -> tuple[bool,list[str]]:
    msgs = []
    try:
        txt = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        txt = path.read_text(errors="ignore")
    original = txt
    mapping = {}

    # images
    img_urls = collect_img_urls_from_text(txt)
    if img_urls:
        ensure_dir(ASSETS_IMG_DIR)
        for url in img_urls:
            ext = preferred_ext(url)
            local_name = filename_from_url(url, prefer_ext=ext)
            local_rel = ASSETS_IMG_DIR / local_name
            local_rel_str = str(local_rel).replace("\\","/")
            if args.no_download:
                if not local_rel.exists():
                    msgs.append(f"⚠ Missing local file (provide it): {local_rel_str}")
            else:
                download(url, local_rel, dry=args.dry_run)
            mapping[url] = local_rel_str

    # mjs modules
    mjs_urls = {m.group(0) for m in FRAMER_MJS_RE.finditer(txt)}
    if mjs_urls:
        ensure_dir(ASSETS_JS_DIR)
        for url in mjs_urls:
            base = filename_from_url(url, prefer_ext=".mjs")
            local_rel = ASSETS_JS_DIR / base
            local_rel_str = str(local_rel).replace("\\","/")
            if args.no_download:
                if not local_rel.exists():
                    msgs.append(f"⚠ Missing local file (provide it): {local_rel_str}")
            else:
                download(url, local_rel, dry=args.dry_run)
            mapping[url] = local_rel_str

    # events script (optional keep)
    if not args.keep_cdn_events:
        for m in EVENTS_SCRIPT_RE.finditer(txt):
            url = m.group(0)
            ensure_dir(ASSETS_JS_DIR)
            local_rel = ASSETS_JS_DIR / "events-script-v2.js"
            local_rel_str = str(local_rel).replace("\\","/")
            if not args.no_download:
                download(url, local_rel, dry=args.dry_run)
            mapping[url] = local_rel_str

    # optional link rewrite (/About -> About.html if About.html exists)
    changed = False
    if args.rewrite_links and path.suffix.lower()==".html":
        def repl_link(m):
            href = m.group("href")
            q    = m.group("q") or ""
            target = href.strip().strip("./").strip("/")
            if not target or "." in target:
                return m.group(0)
            if target in link_map:
                return f'href="{link_map[target]}{q}"'
            if target.lower() in link_map:
                return f'href="{link_map[target.lower()]}{q}"'
            return m.group(0)
        HREF_RE = re.compile(r'href="(?P<href>[^"#?]+)(?P<q>\?[^"]*)?"')
        txt2 = HREF_RE.sub(repl_link, txt)
        if not args.dry_run and txt2 != txt:
            txt = txt2
            changed = True

    # apply asset rewrites
    if mapping:
        if args.dry_run:
            msgs.append(f"DRYRUN: would update -> {path.name}")
        else:
            new_txt = replace_all(txt, mapping)
            if new_txt != original or changed:
                path.write_text(new_txt, encoding="utf-8")
                msgs.append(f"Updated -> {path.name}")
                changed = True
            else:
                msgs.append(f"No changes -> {path.name}")
    else:
        if changed and not args.dry_run:
            path.write_text(txt, encoding="utf-8")
            msgs.append(f"Rewrote links -> {path.name}")
        else:
            msgs.append(f"No changes -> {path.name}")

    return changed, msgs

def build_link_map(root: Path) -> dict[str,str]:
    link_map = {}
    for p in root.glob("*.html"):
        name = p.stem
        link_map[name] = p.name
        link_map[name.lower()] = p.name
    return link_map

# ---------- ensure Framer tags (CSS/JS) in every HTML
CSS_TAG_RE  = re.compile(r'<link[^>]+href=["\']assets/css/framer\.css["\']', re.I)
EVT_TAG_RE  = re.compile(r'<script[^>]+src=["\']assets/js/framer/events-script-v2\.js["\']', re.I)
MAIN_TAG_RE = re.compile(r'<script[^>]+type=["\']module["\'][^>]+src=["\']assets/js/framer/script_main\.Bw_SFk1g\.mjs["\']', re.I)

def ensure_framer_tags(file_path: Path) -> bool:
    """Ensure <head> has framer.css and </body> has events + main module. Returns True if changed."""
    try:
        html = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        html = file_path.read_text(errors="ignore")

    changed = False

    # CSS in <head>
    if not CSS_TAG_RE.search(html):
        html = re.sub(r'(?i)</head>', f'  <link rel="stylesheet" href="{FRAMER_CSS_HREF}">\n</head>', html, count=1)
        changed = True

    # events script before </body>
    if not EVT_TAG_RE.search(html):
        html = re.sub(r'(?i)</body>', f'  <script src="{EVENTS_LOCAL}"></script>\n</body>', html, count=1)
        changed = True

    # main module before </body>
    if not MAIN_TAG_RE.search(html):
        html = re.sub(r'(?i)</body>', f'  <script type="module" src="{MAIN_MODULE}"></script>\n</body>', html, count=1)
        changed = True

    if changed:
        file_path.write_text(html, encoding="utf-8")
        print(f"EnsureTags: fixed -> {file_path.name}")
    return changed

# ---------- driver
def main():
    ap = argparse.ArgumentParser(description="Localize Framer assets and ensure HTML has required CSS/JS.")
    ap.add_argument("--recursive", action="store_true", help="Process files in subfolders too.")
    ap.add_argument("--include-css", action="store_true", help="Also scan .css files for framerusercontent.com URLs.")
    ap.add_argument("--dry-run", action="store_true", help="Preview actions; don't write or download files.")
    ap.add_argument("--no-download", action="store_true", help="Don't download; only rewrite if local files already exist.")
    ap.add_argument("--keep-cdn-events", action="store_true", help="Keep events.framer.com script on CDN.")
    ap.add_argument("--rewrite-links", action="store_true", help="Rewrite internal links like /About -> About.html.")
    args = ap.parse_args()

    root = Path(".").resolve()
    patterns = ["*.html"]
    if args.include_css:
        patterns.append("assets/css/*.css")

    files = []
    if args.recursive:
        for pat in patterns: files += list(root.rglob(pat))
    else:
        for pat in patterns: files += list(root.glob(pat))
    if not files:
        print("No files found."); return

    link_map = build_link_map(root) if args.rewrite_links else {}

    any_changed = False
    for f in sorted(files):
        # Only process CSS with asset rewrites; HTML does both assets and tags
        if f.suffix.lower() == ".css":
            try:
                txt = f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                txt = f.read_text(errors="ignore")
            original = txt
            mapping = {}
            # localize framer images inside CSS url(...)
            img_urls = set()
            for m in CSS_URL_RE.finditer(txt):
                u = m.group("u")
                if is_framer(u) and looks_image(u):
                    img_urls.add(u)
            if img_urls:
                ensure_dir(ASSETS_IMG_DIR)
                for url in img_urls:
                    ext = preferred_ext(url)
                    local_name = filename_from_url(url, prefer_ext=ext)
                    local_rel = ASSETS_IMG_DIR / local_name
                    local_rel_str = str(local_rel).replace("\\","/")
                    if args.no_download:
                        if not local_rel.exists():
                            print(f"⚠ Missing local file (provide it): {local_rel_str}")
                    else:
                        download(url, local_rel, dry=args.dry_run)
                    mapping[url] = local_rel_str
            if mapping and not args.dry_run:
                new_txt = replace_all(txt, mapping)
                if new_txt != original:
                    f.write_text(new_txt, encoding="utf-8")
                    print(f"Updated -> {f}")
                    any_changed = True
            continue

        # HTML path
        changed, msgs = process_file(f, args, link_map)
        for m in msgs: print(m)
        any_changed |= changed

        # Ensure Framer tags on HTML files (only when not dry-run)
        if f.suffix.lower()==".html" and not args.dry_run:
            if ensure_framer_tags(f):
                any_changed = True

    if args.dry_run:
        print("\nDRYRUN complete.")
    else:
        print("\nDone. Files were{} updated.".format("" if any_changed else " not"))

if __name__ == "__main__":
    main()
