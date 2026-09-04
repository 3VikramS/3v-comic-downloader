#!/usr/bin/env python3
"""
Generic page-image downloader / PDF compiler.

Intended for pulling image sequences from pages you have the right to save
from: your own uploads, public-domain archives, or chapters an official site
publishes for free. It has no knowledge of any particular site and will not
work around logins, paywalls, or anti-scraping measures.

Usage:
    python comic_downloader.py <url> [options]

Examples:
    python comic_downloader.py https://example.com/chapter-1 -o out/chapter-1
    python comic_downloader.py https://example.com/chapter-1 --selector ".reader img" --pdf
"""
from __future__ import annotations

import argparse
import io
import re
import sys
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

Logger = Callable[[str], None]

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Attributes that commonly carry the real image URL, checked in order.
IMG_SRC_ATTRS = ["src", "data-src", "data-lazy-src", "data-original", "data-url"]

# URL path fragments that are almost never chapter art (nav icons, avatars, ads).
SKIP_PATTERNS = re.compile(
    r"(logo|icon|avatar|banner|ads?[-_/]|sprite|favicon)", re.IGNORECASE
)


def fetch(url: str, session: requests.Session) -> str:
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    return resp.text


def extract_image_urls(html: str, base_url: str, selector: str | None) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    scope = soup.select(selector) if selector else soup.find_all("img")
    if selector and not scope:
        raise ValueError(f"CSS selector {selector!r} matched no elements on the page")

    urls: list[str] = []
    seen: set[str] = set()
    for img in scope:
        tag = img if img.name == "img" else img.find("img")
        if tag is None:
            continue
        raw = next((tag.get(attr) for attr in IMG_SRC_ATTRS if tag.get(attr)), None)
        if not raw:
            continue
        full = urljoin(base_url, raw.strip())
        if full in seen:
            continue
        if not selector and SKIP_PATTERNS.search(full):
            continue
        seen.add(full)
        urls.append(full)
    return urls


def guess_extension(url: str, content_type: str | None) -> str:
    path_ext = Path(urlparse(url).path).suffix.lower()
    if path_ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return path_ext
    if content_type:
        mapping = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }
        for mime, ext in mapping.items():
            if mime in content_type:
                return ext
    return ".jpg"


def validate_image(content: bytes) -> str | None:
    """Return None if content is a decodable image, else a short reason it isn't."""
    try:
        with Image.open(io.BytesIO(content)) as im:
            im.verify()
        return None
    except UnidentifiedImageError:
        return "response body is not a recognizable image (HTML error page? empty body?)"
    except Exception as exc:  # noqa: BLE001 - surface any decode failure, not just PIL's own
        return f"image failed to decode ({exc})"


def download_images(
    urls: list[str],
    out_dir: Path,
    session: requests.Session,
    referer: str,
    delay: float,
    log: Logger = print,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    width = len(str(len(urls)))
    for i, url in enumerate(urls, 1):
        resp = session.get(url, headers={"Referer": referer}, timeout=20)
        resp.raise_for_status()

        problem = validate_image(resp.content)
        if problem:
            log(f"  [{i}/{len(urls)}] SKIPPED {url} - {problem}")
            if delay:
                time.sleep(delay)
            continue

        ext = guess_extension(url, resp.headers.get("Content-Type"))
        dest = out_dir / f"{i:0{width}d}{ext}"
        dest.write_bytes(resp.content)
        saved.append(dest)
        log(f"  [{i}/{len(urls)}] saved {dest.name}")
        if delay:
            time.sleep(delay)

    if not saved:
        raise ValueError("None of the found URLs were decodable images - nothing to save.")
    return saved


def build_pdf(image_paths: list[Path], pdf_path: Path, log: Logger = print) -> None:
    import img2pdf

    with open(pdf_path, "wb") as f:
        f.write(img2pdf.convert([str(p) for p in image_paths]))
    log(f"Wrote PDF: {pdf_path}")


def slugify(url: str) -> str:
    path = urlparse(url).path.strip("/")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-").lower()
    return slug or "output"


def run_job(
    url: str,
    out_dir: Path,
    selector: str | None = None,
    make_pdf: bool = False,
    delay: float = 0.5,
    user_agent: str = DEFAULT_UA,
    log: Logger = print,
) -> list[Path]:
    """Run the full fetch -> extract -> download (-> pdf) pipeline. Returns saved image paths."""
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})

    log(f"Fetching {url}")
    html = fetch(url, session)

    urls = extract_image_urls(html, url, selector)
    if not urls:
        raise ValueError("No images found. Try a --selector to target the reader container.")
    log(f"Found {len(urls)} image(s)")

    saved = download_images(urls, out_dir, session, referer=url, delay=delay, log=log)

    if make_pdf:
        build_pdf(saved, out_dir.with_suffix(".pdf"), log=log)

    log(f"Done. Images saved to {out_dir}")
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="Page URL to pull images from")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output directory (default: derived from URL)")
    parser.add_argument("--selector", default=None, help="CSS selector scoping which <img> elements to grab")
    parser.add_argument("--pdf", action="store_true", help="Also compile downloaded images into a PDF")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds to wait between image downloads (default: 0.5)")
    parser.add_argument("--user-agent", default=DEFAULT_UA, help="Custom User-Agent header")
    args = parser.parse_args()

    out_dir = args.output or Path(slugify(args.url))

    try:
        run_job(
            args.url,
            out_dir,
            selector=args.selector,
            make_pdf=args.pdf,
            delay=args.delay,
            user_agent=args.user_agent,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
