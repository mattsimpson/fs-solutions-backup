#!/usr/bin/env python3
"""
Freshservice Solutions Knowledge Base Backup

Exports the complete Freshservice Solutions KB (Categories > Folders > Articles)
to local Markdown files with YAML frontmatter, ready for Retype static site
generation.

MIT License

Copyright (c) 2026 Matt Simpson

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import os
import re
import sys
import time
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from markdownify import markdownify as md


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

DOMAIN = os.getenv("FRESHSERVICE_DOMAIN", "").strip().rstrip("/")
API_KEY = os.getenv("FRESHSERVICE_API_KEY", "").strip()
BASE_URL = f"https://{DOMAIN}/api/v2"
OUTPUT_DIR = Path("solutions")
REQUEST_DELAY = 0.2  # seconds between requests
MAX_RETRIES = 3
PER_PAGE = 100
ALLOWED_IMAGE_HOSTS = {
    "freshservice.com",
    "freshdesk.com",
    "freshworks.com",
    "amazonaws.com",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_session() -> requests.Session:
    """Create a requests session with Freshservice basic auth."""
    session = requests.Session()
    session.auth = (API_KEY, "X")
    session.headers.update({"Content-Type": "application/json"})
    return session


def sanitize_filename(name: str, max_len: int = 200) -> str:
    """Remove filesystem-unsafe characters and truncate."""
    name = re.sub(r'[/\\:*?"<>|]', "", name)
    name = name.replace("..", "")  # prevent path traversal
    name = re.sub(r"  +", " ", name)  # collapse any double spaces left behind
    name = name.strip().strip(".")
    if len(name) > max_len:
        name = name[:max_len]
    return name or "untitled"


def respect_rate_limit(response: requests.Response) -> None:
    """Sleep if we're close to the rate limit."""
    remaining = response.headers.get("X-RateLimit-Remaining")
    if remaining is not None and int(remaining) < 5:
        time.sleep(1)


def api_get(session: requests.Session, url: str, params: dict | None = None) -> requests.Response:
    """GET with retries, rate-limit handling, and polite delay."""
    for attempt in range(1, MAX_RETRIES + 1):
        time.sleep(REQUEST_DELAY)
        try:
            resp = session.get(url, params=params, timeout=30)
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise
            print(f"  [retry {attempt}/{MAX_RETRIES}] Request error: {exc}")
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 429:
            retry_after = min(int(resp.headers.get("Retry-After", 30)), 300)
            print(f"  Rate limited — sleeping {retry_after}s …")
            time.sleep(retry_after)
            continue

        if resp.status_code >= 500 and attempt < MAX_RETRIES:
            print(f"  [retry {attempt}/{MAX_RETRIES}] Server error {resp.status_code}")
            time.sleep(2 ** attempt)
            continue

        resp.raise_for_status()
        respect_rate_limit(resp)
        return resp

    # Should not reach here, but just in case
    resp.raise_for_status()
    return resp


def paginate(session: requests.Session, url: str, params: dict | None = None) -> list[dict]:
    """Fetch all pages from a paginated Freshservice endpoint."""
    params = dict(params or {})
    params["per_page"] = PER_PAGE
    page = 1
    results: list[dict] = []

    while True:
        params["page"] = page
        resp = api_get(session, url, params)
        data = resp.json()

        # The API wraps results in a top-level key (e.g. "categories", "folders", "articles")
        for key in data:
            if isinstance(data[key], list):
                results.extend(data[key])
                break

        # Check for next page via Link header
        link = resp.headers.get("Link", "")
        if 'rel="next"' in link:
            page += 1
        else:
            break

    return results


# ---------------------------------------------------------------------------
# Image downloading
# ---------------------------------------------------------------------------

def slug_from_title(title: str) -> str:
    """Create a URL-style slug from an article title."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:60]


def is_allowed_image_url(url: str) -> bool:
    """Check that an image URL uses HTTPS and belongs to an allowed host."""
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        return False
    host = parsed.hostname or ""
    return any(host == domain or host.endswith("." + domain)
               for domain in ALLOWED_IMAGE_HOSTS)


def download_image(auth_session: requests.Session, img_url: str, dest: Path) -> bool:
    """Download a single image. Returns True on success.

    Uses the authenticated session only for allowed Freshservice hosts;
    falls back to an unauthenticated request for any other allowed host.
    """
    if not is_allowed_image_url(img_url):
        print(f"    SKIPPED: untrusted image host — {img_url}")
        return False

    # Only send credentials to Freshservice domains
    parsed = urlparse(img_url)
    host = parsed.hostname or ""
    use_auth = host.endswith("freshservice.com") or host.endswith("freshdesk.com")
    session = auth_session if use_auth else requests.Session()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            time.sleep(REQUEST_DELAY)
            resp = session.get(img_url, timeout=30, stream=True)
            if resp.status_code == 200:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                return True
            elif resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 30))
                time.sleep(retry_after)
                continue
            else:
                print(f"    WARNING: Image {resp.status_code} — {img_url}")
                return False
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                print(f"    WARNING: Image download failed — {exc}")
                return False
            time.sleep(2 ** attempt)
    return False


def guess_extension(url: str, default: str = ".png") -> str:
    """Guess image file extension from the URL path."""
    path = urlparse(url).path
    ext = Path(path).suffix.lower()
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico"):
        return ext
    # Try mimetypes as fallback
    guessed = mimetypes.guess_extension(mimetypes.guess_type(url)[0] or "")
    return guessed if guessed else default


def process_images(session: requests.Session, html: str, article_title: str,
                   images_dir: Path) -> tuple[str, int]:
    """Extract images from HTML, download them, and rewrite src to relative paths.

    Returns (rewritten_html, download_count).
    """
    soup = BeautifulSoup(html, "html.parser")
    img_tags = soup.find_all("img")
    if not img_tags:
        return html, 0

    slug = slug_from_title(article_title)
    img_count = 0
    downloaded = 0

    for tag in img_tags:
        src = tag.get("src")
        if not src:
            continue

        img_count += 1
        ext = guess_extension(src)
        filename = f"{slug}-img{img_count:03d}{ext}"
        dest = images_dir / filename

        if download_image(session, src, dest):
            downloaded += 1
            # Rewrite to relative path (relative to the article's folder)
            tag["src"] = f"./images/{filename}"
        # If download fails, leave original src

    rewritten = str(soup) if img_count > 0 else html
    return rewritten, downloaded


def download_attachments(session: requests.Session, attachments: list[dict],
                         article_title: str, images_dir: Path) -> int:
    """Download formal attachments from the article's attachments array."""
    if not attachments:
        return 0

    slug = slug_from_title(article_title)
    downloaded = 0

    for i, att in enumerate(attachments, 1):
        url = att.get("attachment_url") or att.get("content_url")
        if not url:
            continue

        name = att.get("name", "")
        ext = Path(name).suffix if name else guess_extension(url, ".bin")
        filename = f"{slug}-att{i:03d}{ext}"
        dest = images_dir / filename

        if download_image(session, url, dest):
            downloaded += 1

    return downloaded


# ---------------------------------------------------------------------------
# Markdown generation
# ---------------------------------------------------------------------------

def yaml_escape(value: str) -> str:
    """Escape a string for safe inclusion in YAML."""
    if any(c in value for c in '":{}[]|>&*!#%@`'):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def article_frontmatter(article: dict, order: int) -> str:
    """Build YAML frontmatter for an article (Retype-compatible)."""
    tags = article.get("tags") or []
    tags_yaml = "\n".join(f"  - {yaml_escape(t)}" for t in tags) if tags else ""
    status = status_label(article.get("status"))

    # Use updated_at for Retype's date field, fall back to created_at
    date = article.get("updated_at") or article.get("created_at") or ""
    # Retype wants yyyy-mm-dd or yyyy-mm-ddThh:mm — trim if needed
    if date and "T" in date:
        date = date[:19]  # "2024-01-15T10:30:00"

    lines = [
        "---",
        f"label: {yaml_escape(article.get('title', ''))}",
        f"order: {order}",
        f'date: "{date}"',
    ]
    # Mark drafts as hidden in Retype
    if status == "draft":
        lines.append("visibility: hidden")
    if tags_yaml:
        lines.append("tags:")
        lines.append(tags_yaml)
    else:
        lines.append("tags: []")
    lines += [
        f"id: {article['id']}",
        f'status: "{status}"',
        f"author_id: {article.get('agent_id', '')}",
        f'created_at: "{article.get("created_at", "")}"',
        f'updated_at: "{article.get("updated_at", "")}"',
        f"folder_id: {article.get('folder_id', '')}",
        f"category_id: {article.get('category_id', '')}",
        f"views: {article.get('hits', 0)}",
        f"thumbs_up: {article.get('thumbs_up', 0)}",
        f"thumbs_down: {article.get('thumbs_down', 0)}",
        "---",
    ]
    return "\n".join(lines)


def status_label(status: int | None) -> str:
    """Convert Freshservice numeric status to label."""
    return {1: "draft", 2: "published"}.get(status, f"unknown({status})")


def write_category_index(cat: dict, path: Path) -> None:
    """Write index.md for a category directory (Retype folder page)."""
    description = cat.get("description") or ""
    position = cat.get("position", 100)
    content = (
        f"---\n"
        f"label: {yaml_escape(cat.get('name', 'Untitled'))}\n"
        f"order: {position}\n"
        f"expanded: true\n"
        f"icon: book\n"
        f"id: {cat['id']}\n"
        f"---\n\n"
        f"# {cat.get('name', 'Untitled')}\n\n"
        f"{description}\n"
    )
    path.write_text(content, encoding="utf-8")


def write_folder_index(folder: dict, path: Path) -> None:
    """Write index.md for a folder directory (Retype folder page)."""
    visibility_map = {1: "All Users", 2: "Logged-in Users", 3: "Agents Only"}
    visibility = visibility_map.get(folder.get("visibility"), str(folder.get("visibility", "")))
    description = folder.get("description") or ""
    position = folder.get("position", 100)

    # Map Freshservice visibility to Retype visibility
    retype_vis = ""
    if folder.get("visibility") == 3:
        retype_vis = "visibility: hidden\n"

    content = (
        f"---\n"
        f"label: {yaml_escape(folder.get('name', 'Untitled'))}\n"
        f"order: {position}\n"
        f"expanded: false\n"
        f"icon: file-directory\n"
        f"{retype_vis}"
        f"id: {folder['id']}\n"
        f"freshservice_visibility: \"{visibility}\"\n"
        f"---\n\n"
        f"# {folder.get('name', 'Untitled')}\n\n"
        f"{description}\n"
    )
    path.write_text(content, encoding="utf-8")


def write_retype_config(output_dir: Path, domain: str) -> None:
    """Write retype.yml configuration file."""
    # Extract a clean title from the domain
    title = domain.split(".")[0].replace("-", " ").title() if domain else "Knowledge Base"

    content = (
        f"input: .\n"
        f"output: .retype\n"
        f"url: {domain}\n"
        f"branding:\n"
        f"  title: \"{title} KB\"\n"
        f"  label: Knowledge Base\n"
        f"footer:\n"
        f"  copyright: \"Exported from Freshservice Solutions\"\n"
        f"search:\n"
        f"  hotkeys:\n"
        f"    - /\n"
    )
    (output_dir / "retype.yml").write_text(content, encoding="utf-8")


def write_homepage(output_dir: Path, totals: dict) -> None:
    """Write the root index.md homepage for Retype."""
    content = (
        "---\n"
        "label: Home\n"
        "icon: home\n"
        "---\n\n"
        "# Knowledge Base\n\n"
        "Offline archive of Freshservice Solutions articles.\n\n"
        f"- **Categories:** {totals['categories']}\n"
        f"- **Folders:** {totals['folders']}\n"
        f"- **Articles:** {totals['articles']}\n"
        f"- **Images:** {totals['images']}\n"
    )
    (output_dir / "index.md").write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main export logic
# ---------------------------------------------------------------------------

def export_kb() -> None:
    """Run the full Knowledge Base export."""
    if not DOMAIN or not API_KEY or "yourcompany" in DOMAIN:
        print("ERROR: Set FRESHSERVICE_DOMAIN and FRESHSERVICE_API_KEY in .env")
        sys.exit(1)

    session = build_session()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    totals = {"categories": 0, "folders": 0, "articles": 0, "images": 0}

    # --- Categories ---
    print("Fetching categories …")
    categories = paginate(session, f"{BASE_URL}/solutions/categories")
    totals["categories"] = len(categories)
    print(f"Found {len(categories)} categories.\n")

    for ci, cat in enumerate(categories, 1):
        cat_name = sanitize_filename(cat.get("name", "Untitled"))
        cat_dir = OUTPUT_DIR / cat_name
        cat_dir.mkdir(parents=True, exist_ok=True)
        write_category_index(cat, cat_dir / "index.md")
        print(f"Category: {cat['name']} ({ci}/{len(categories)})")

        # --- Folders ---
        folders = paginate(session, f"{BASE_URL}/solutions/folders",
                           {"category_id": cat["id"]})
        totals["folders"] += len(folders)

        for fi, folder in enumerate(folders, 1):
            folder_name = sanitize_filename(folder.get("name", "Untitled"))
            folder_dir = cat_dir / folder_name
            folder_dir.mkdir(parents=True, exist_ok=True)
            write_folder_index(folder, folder_dir / "index.md")
            print(f"  Folder: {folder['name']} ({fi}/{len(folders)})")

            # --- Articles ---
            articles = paginate(session, f"{BASE_URL}/solutions/articles",
                                {"folder_id": folder["id"]})
            totals["articles"] += len(articles)

            # Track filenames to handle duplicates within this folder
            seen_filenames: dict[str, int] = {}

            for ai, article_summary in enumerate(articles, 1):
                # Fetch full article detail
                resp = api_get(session, f"{BASE_URL}/solutions/articles/{article_summary['id']}")
                article = resp.json().get("article", resp.json())

                title = article.get("title", "Untitled")
                print(f"    Article: {title} ({ai}/{len(articles)})")

                # Process images in HTML body
                body_html = article.get("description") or article.get("description_text") or ""
                images_dir = folder_dir / "images"
                body_html, img_downloaded = process_images(session, body_html, title, images_dir)
                totals["images"] += img_downloaded

                # Download formal attachments
                attachments = article.get("attachments") or []
                att_downloaded = download_attachments(session, attachments, title, images_dir)
                totals["images"] += att_downloaded

                # Convert to Markdown
                body_md = md(body_html, heading_style="ATX", strip=["script", "style"])

                # Build frontmatter
                frontmatter = article_frontmatter(article, order=ai)

                # Determine filename, handling duplicates
                base_name = sanitize_filename(title)
                if base_name in seen_filenames:
                    seen_filenames[base_name] += 1
                    file_name = f"{base_name}-{article['id']}.md"
                else:
                    seen_filenames[base_name] = 1
                    file_name = f"{base_name}.md"

                article_path = folder_dir / file_name
                article_path.write_text(
                    f"{frontmatter}\n\n{body_md.strip()}\n",
                    encoding="utf-8",
                )

    # --- Write Retype config and homepage ---
    write_retype_config(OUTPUT_DIR, DOMAIN)
    write_homepage(OUTPUT_DIR, totals)

    # --- Summary ---
    print("\n" + "=" * 50)
    print("Export complete!")
    print(f"  Categories: {totals['categories']}")
    print(f"  Folders:    {totals['folders']}")
    print(f"  Articles:   {totals['articles']}")
    print(f"  Images:     {totals['images']}")
    print(f"  Output:     {OUTPUT_DIR.resolve()}")
    print()
    print("To view with Retype:")
    print(f"  cd {OUTPUT_DIR} && retype start")
    print("=" * 50)


if __name__ == "__main__":
    export_kb()
