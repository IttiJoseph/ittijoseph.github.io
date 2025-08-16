#!/usr/bin/env python3
"""
framer_localize.py
- Find framerusercontent.com URLs in HTML (and optionally CSS)
- Download images + .mjs runtime files to local assets/
- Rewrite HTML/CSS to point to local copies

Usage examples:
  python framer_localize.py --dry-run
  python framer_localize.py --recursive
  python framer_localize.py --recursive --include-css
  python framer_localize.py --recursive --no-download  (only rewrite if files already present)
"""

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("This script needs the 'requests' package.\nInstall it with:  pip install requests", file=sys.stderr)
    sys.exit(1)


# -----------------------------
# Config / constants
# -----------------------------
IMAGE_EXT_RE = r"(?:png|jpe?g|webp|gif|svg|ico|avif)"
FRAMER_HOST_RE = r"https?://[^\"'\s]*framerusercontent\.com[^\"'\s]*"
FRAMER_IMG_RE = re.compile(
    rf"(?i){FRAMER_HOST_RE}\.(?:{IMAGE_EXT_RE})(?:\?[^\"'\s]*)?"
)
FRAMER_MJS_RE = re.compile(
    rf"(?i){FRAMER_HOST_RE}\.mjs(?:\?[^\"'\s]*)?"
)

# Optional: events script (different host)
EVENTS_SCRIPT_RE = re.compile(r"(?i)https?://events\.framer\.com/script[^\s\"']*")

ASSETS_IMG_DIR = Path("assets/images")
ASSETS_JS_DIR = Path("assets/js/framer")

# -----------------------------
# Helpers
# -----------------------------
def short_hash(s: str, n: int = 6) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:n]

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def filename_from_url(url: str, prefer_ext: str = "") -> str:
    """
    Derive a sane local filename from a URL:
    - base = last path segment
    - if there is a query string, append a short hash before the ext to avoid collisions
    """
    from urllib.parse import urlparse
    u = urlparse(url)
    base = os.path.basename(u.path) or "file"
    name, ext = os.path.splitext(base)

    # If no extension in path but we know the type, apply it
    if not ext and prefer_ext:
        ext = prefer_ext if prefer_ext.startswith(".") else f".{prefer_ext}"

    if u.query:
        h = short_hash(url, 6)
        base = f"{name}.{h}{ext}"
    else:
        base = f"{name}{ext}"

    return base

def download(url: str, dest: Path, dry_run: bool = False) -> bool:
    if dest.exists():
        # already there
        return True
    if dry_run:
        print(f"  DRYRUN: would download -> {dest}")
        return True
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        print(f"  OK: {url} -> {dest}")
        return True
    except Exception as e:
        print(f"  ERROR: download failed {url}  ({e})")
        return False

def replace_all(text: str, mapping: dict) -> str:
    """Replace each exact key with its value in the text."""
    for old, new in mapping.items():
        text = text.replace(old, new)
    return text

def find_all(pattern: re.Pattern, text: str) -> list[str]:
    return list({m.group(0) for m in pattern.finditer(text)})


# -----------------------------
# Processing functions
# -----------------------------
def process_one_file(path: Path, args) -> tuple[bool, list[str]]:
    """
    Returns: (changed, messages)
    """
    msgs = []
    try:
        txt = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # try default
        txt = path.read_text(errors="ignore")

    original = txt

    # Collect URLs
    img_urls = find_all(FRAMER_IMG_RE, txt)
    mjs_urls = find_all(FRAMER_MJS_RE, txt)
    events_urls = find_all(EVENTS_SCRIPT_RE, txt) if not args.keep_cdn_events else []

    mapping = {}

    # Images
    if img_urls:
        ensure_dir(ASSETS_IMG_DIR)
        for url in img_urls:
            # derive extension to prefer (if no ext in path)
            ext_match = re.search(rf"\.({IMAGE_EXT_RE})\b", url, flags=re.I)
            prefer_ext = f".{ext_match.group(1).lower()}" if ext_match else ""
            local_name = filename_from_url(url, prefer_ext=prefer_ext)
            local_rel = ASSETS_IMG_DIR / local_name
            local_rel_str = str(local_rel).replace("\\", "/")
            if args.no_download:
                if not Path(local_rel).exists():
                    msgs.append(f"⚠ Missing local file (provide it): {local_rel_str}")
            else:
                download(url, Path(local_rel), dry_run=args.dry_run)
            mapping[url] = local_rel_str

    # JS modules (.mjs)
    if mjs_urls:
        ensure_dir(ASSETS_JS_DIR)
        for url in mjs_urls:
            # only rename by basename; keep exact file name so imports match
            base = filename_from_url(url, prefer_ext=".mjs")
            local_rel = ASSETS_JS_DIR / base
            local_rel_str = str(local_rel).replace("\\", "/")
            if args.no_download:
                if not Path(local_rel).exists():
                    msgs.append(f"⚠ Missing local file (provide it): {local_rel_str}")
            else:
                download(url, Path(local_rel), dry_run=args.dry_run)
            mapping[url] = local_rel_str

    # Events script (optional)
    for url in events_urls:
        # store locally as events-script-v2.js
        ensure_dir(ASSETS_JS_DIR)
        local_rel = ASSETS_JS_DIR / "events-script-v2.js"
        local_rel_str = str(local_rel).replace("\\", "/")
        if not args.no_download:
            download(url, Path(local_rel), dry_run=args.dry_run)
        mapping[url] = local_rel_str

    # Rewrite file if needed
    if mapping and not args.dry_run:
        txt_new = replace_all(txt, mapping)
        if txt_new != original:
            path.write_text(txt_new, encoding="utf-8")
            msgs.append(f"Updated -> {path.name}")
            return True, msgs

    # Dry run summary
    if mapping and args.dry_run:
        msgs.append(f"DRYRUN: would update -> {path.name}")
        return False, msgs

    msgs.append(f"No changes -> {path.name}")
    return False, msgs


def process_tree(args):
    root = Path(".").resolve()
    patterns = ["*.html"]
    if args.include_css:
        patterns.append("*.css")

    # gather files
    files: list[Path] = []
    if args.recursive:
        for pat in patterns:
            files.extend(root.rglob(pat))
    else:
        for pat in patterns:
            files.extend(root.glob(pat))

    if not files:
        print("No files found to process.")
        return

    any_changed = False
    for f in sorted(files):
        changed, msgs = process_one_file(f, args)
        any_changed = any_changed or changed
        for m in msgs:
            print(m)

    if args.dry_run:
        print("\nDRYRUN complete.")
    else:
        if any_changed:
            print("\nDone. Files were updated.")
        else:
            print("\nDone. Nothing to update.")


# -----------------------------
# CLI
# -----------------------------
def main():
    p = argparse.ArgumentParser(description="Localize Framer images and JS (.mjs) and rewrite HTML/CSS.")
    p.add_argument("--recursive", action="store_true", help="Process files in subfolders too.")
    p.add_argument("--include-css", action="store_true", help="Also scan .css files for framerusercontent.com URLs.")
    p.add_argument("--dry-run", action="store_true", help="Preview actions; don't write or download files.")
    p.add_argument("--no-download", action="store_true", help="Don't download; only rewrite if local files already exist.")
    p.add_argument("--keep-cdn-events", action="store_true", help="Keep events.framer.com script on CDN.")
    args = p.parse_args()
    process_tree(args)


if __name__ == "__main__":
    main()
