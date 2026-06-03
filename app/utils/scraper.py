#!/usr/bin/env python3
"""
Kehulum EUEE Scraper
=====================
Scrapes EUEE questions from kehulum.com — including image download.

Output schema per exam:
  {
    "Subject": "Physics",
    "Year": "2016",
    "Stream": "natural",
    "Questions": [
      {
        "Number": 7,
        "Question": "Three charges Q1 = ...",
        "Question_image": {               ← null when no diagram in question body
          "url": "https://kehulum.com/queimgs/...",
          "local_path": "images/natural_2016_physics/q7_body.webp"
        },
        "Choices": [
          { "letter": "A", "text": "3.6 x 10-6 N", "image": null },
          { "letter": "B", "text": "9 x 10-7 N",   "image": null }
        ],
        "Correct_choice": null
      },
      {
        "Number": 3,
        "Question": "Which circuit symbol is matched...",
        "Question_image": null,
        "Choices": [
          { "letter": "A", "text": null, "image": {   ← image choice
              "url": "https://kehulum.com/queimgs/...",
              "local_path": "images/natural_2016_physics/q3_A.webp"
            }
          }
        ],
        "Correct_choice": null
      }
    ]
  }

Requirements:
    pip install requests beautifulsoup4 lxml

Usage:
    python kehulum_scraper.py                              # everything
    python kehulum_scraper.py --stream natural --year 2016
    python kehulum_scraper.py --stream natural --year 2016 --subject physics
    python kehulum_scraper.py --no-csv
"""

import argparse
import csv
import json
import mimetypes
import os
import re
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from bs4.exceptions import FeatureNotFound

# ── Config ───────────────────────────────────────────────────────────────────

BASE_URL = "https://kehulum.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://kehulum.com/",
}

PAGE_DELAY  = 1.5   # seconds between page fetches
IMAGE_DELAY = 0.5   # seconds between image downloads

CHOICE_LETTERS = {"A", "B", "C", "D", "E"}

SKIP_TEXTS = {
    "share", "show explanation", "login", "create account",
    "please login to load more comments",
    "please login/create account to add comment or answer",
    "no explanation yet — share your knowledge!",
    "no comments yet. add your answer or start the discussion!",
    "advertisement",
}

# ── Subject catalogue ────────────────────────────────────────────────────────

SUBJECTS = {
    "natural": {
        "2013": [
            {"name": "Biology",                  "slug": "biology-104"},
            {"name": "Chemistry",                "slug": "chemistry-105"},
            {"name": "English",                  "slug": "english-108"},
            {"name": "Mathematics",              "slug": "mathematics-107"},
            {"name": "Physics",                  "slug": "physics-106"},
            {"name": "Scholastic Aptitude Test", "slug": "scholastic-aptitude-test-133"},
        ],
        "2014": [
            {"name": "Biology",                  "slug": "biology-109"},
            {"name": "Chemistry",                "slug": "chemistry-110"},
            {"name": "English",                  "slug": "english-113"},
            {"name": "Mathematics",              "slug": "mathematics-112"},
            {"name": "Physics",                  "slug": "physics-111"},
            {"name": "Scholastic Aptitude Test", "slug": "scholastic-aptitude-test-134"},
        ],
        "2015": [
            {"name": "Biology",                  "slug": "biology-144"},
            {"name": "Chemistry",                "slug": "chemistry-145"},
            {"name": "English",                  "slug": "english-148"},
            {"name": "Mathematics",              "slug": "mathematics-147"},
            {"name": "Physics",                  "slug": "physics-146"},
            {"name": "Scholastic Aptitude Test", "slug": "scholastic-aptitude-test-135"},
        ],
        "2016": [
            {"name": "Biology",                  "slug": "biology-182"},
            {"name": "Chemistry",                "slug": "chemistry-183"},
            {"name": "English",                  "slug": "english-186"},
            {"name": "Mathematics",              "slug": "mathematics-185"},
            {"name": "Physics",                  "slug": "physics-184"},
            {"name": "Scholastic Aptitude Test", "slug": "scholastic-aptitude-test-175"},
            {"name": "Tigray Biology",           "slug": "tigray-region-biology-206"},
            {"name": "Tigray Chemistry",         "slug": "tigray-region-chemistry-207"},
            {"name": "Tigray Civics",            "slug": "tigray-region-civics-208"},
            {"name": "Tigray English",           "slug": "tigray-region-english-209"},
            {"name": "Tigray Mathematics",       "slug": "tigray-region-mathematics-210"},
            {"name": "Tigray Physics",           "slug": "tigray-region-physics-211"},
            {"name": "Tigray SAT",               "slug": "tigray-region-scholastic-aptitude-test-205"},
        ],
        "2017": [
            {"name": "Biology",                  "slug": "biology-215"},
            {"name": "Chemistry",                "slug": "chemistry-216"},
            {"name": "English",                  "slug": "english-219"},
            {"name": "Mathematics",              "slug": "mathematics-218"},
            {"name": "Physics",                  "slug": "physics-217"},
            {"name": "Scholastic Aptitude Test", "slug": "scholastic-aptitude-test-214"},
        ],
    },
    "social": {
        "2013": [
            {"name": "Civics",                   "slug": "civics-114"},
            {"name": "Economics",                "slug": "economics-117"},
            {"name": "English",                  "slug": "english-118"},
            {"name": "Geography",                "slug": "geography-115"},
            {"name": "History",                  "slug": "history-116"},
            {"name": "Mathematics",              "slug": "mathematics-119"},
            {"name": "Scholastic Aptitude Test", "slug": "scholastic-aptitude-test-136"},
        ],
        "2014": [
            {"name": "Civics",                   "slug": "civics-120"},
            {"name": "Economics",                "slug": "economics-123"},
            {"name": "English",                  "slug": "english-124"},
            {"name": "Geography",                "slug": "geography-121"},
            {"name": "History",                  "slug": "history-122"},
            {"name": "Mathematics",              "slug": "mathematics-125"},
            {"name": "Scholastic Aptitude Test", "slug": "scholastic-aptitude-test-137"},
        ],
        "2015": [
            {"name": "Civics",                   "slug": "civics-149"},
            {"name": "Economics",                "slug": "economics-152"},
            {"name": "English",                  "slug": "english-153"},
            {"name": "Geography",                "slug": "geography-150"},
            {"name": "History",                  "slug": "history-151"},
            {"name": "Mathematics",              "slug": "mathematics-154"},
            {"name": "Scholastic Aptitude Test", "slug": "scholastic-aptitude-test-138"},
        ],
        "2016": [
            {"name": "Civics",                   "slug": "civics-187"},
            {"name": "Economics",                "slug": "economics-190"},
            {"name": "English",                  "slug": "english-191"},
            {"name": "Geography",                "slug": "geography-188"},
            {"name": "History",                  "slug": "history-189"},
            {"name": "Mathematics",              "slug": "mathematics-192"},
            {"name": "Scholastic Aptitude Test", "slug": "scholastic-aptitude-test-176"},
        ],
        "2017": [
            {"name": "Civics",                   "slug": "civics-220"},
            {"name": "Economics",                "slug": "economics-223"},
            {"name": "English",                  "slug": "english-224"},
            {"name": "Geography",                "slug": "geography-221"},
            {"name": "History",                  "slug": "history-222"},
            {"name": "Mathematics",              "slug": "mathematics-225"},
            {"name": "Scholastic Aptitude Test", "slug": "scholastic-aptitude-test-213"},
        ],
    },
}

# ── HTTP session ─────────────────────────────────────────────────────────────

session = requests.Session()
session.headers.update(HEADERS)
_FALLBACK_PARSER_WARNED = False


def fetch(url, retries=3, stream=False):
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=30, stream=stream)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"    [ERROR] {url} → {e}")
    return None


def get_soup(url):
    r = fetch(url)
    if not r:
        return None

    try:
        return BeautifulSoup(r.text, "lxml")
    except FeatureNotFound:
        global _FALLBACK_PARSER_WARNED
        if not _FALLBACK_PARSER_WARNED:
            print("    [WARN] lxml parser not available; using html.parser fallback")
            _FALLBACK_PARSER_WARNED = True
        return BeautifulSoup(r.text, "html.parser")


def is_not_found_page(page_soup) -> bool:
    """Detect Kehulum not-found/no-result pages."""
    if page_soup is None:
        return False
    for tag in page_soup.find_all(["h1", "h2"]):
        txt = clean(tag.get_text(" ", strip=True)).lower()
        if "not found" in txt or "no result" in txt:
            return True
    return False


def _slug_stem(slug: str) -> str:
    """Drop trailing numeric identifier from slug, e.g. biology-104 -> biology."""
    return re.sub(r"-\d+$", "", slug)


def resolve_subject_slug(stream: str, year: str, subject: dict) -> str | None:
    """Find current subject slug from the year listing page."""
    year_url = f"{BASE_URL}/entrance-exam/{stream}-science/{year}"
    year_soup = get_soup(year_url)
    if year_soup is None:
        return None

    expected_prefix = f"/entrance-exam/{stream}-science/{year}/"
    links = []
    for a in year_soup.find_all("a", href=True):
        href = a["href"]
        parsed = urllib.parse.urlparse(href)
        path = parsed.path
        if path.startswith(expected_prefix):
            candidate = path[len(expected_prefix):].strip("/")
            if candidate:
                links.append(candidate)

    if not links:
        return None

    # 1) Best match: same slug stem, different numeric id.
    wanted_stem = _slug_stem(subject.get("slug", ""))
    if wanted_stem:
        for cand in links:
            if _slug_stem(cand) == wanted_stem:
                return cand

    # 2) Fallback: normalized subject name appears in slug.
    wanted_name = re.sub(r"[^a-z0-9]+", "-", subject.get("name", "").lower()).strip("-")
    if wanted_name:
        for cand in links:
            if wanted_name in cand:
                return cand

    return None


# ── Image downloading ─────────────────────────────────────────────────────────

def abs_url(src):
    """Ensure image src is an absolute URL."""
    if src.startswith("http"):
        return src
    return BASE_URL + src


def ext_from_url(url):
    """Guess file extension from URL path."""
    path = urllib.parse.urlparse(url).path
    _, ext = os.path.splitext(path)
    return ext.lower() if ext else ".webp"


def download_image(url, dest_path: Path) -> bool:
    """
    Download a single image to dest_path.
    Returns True on success, False on failure.
    Skips download if file already exists.
    """
    if dest_path.exists():
        return True
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    r = fetch(url, stream=True)
    if r is None:
        return False
    try:
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except OSError as e:
        print(f"    [ERROR] Could not write {dest_path}: {e}")
        return False


def image_record(url, local_path: Path, img_root: Path) -> dict:
    """
    Build the image sub-object used in the JSON.
    local_path is relative to img_root for portability.
    """
    try:
        rel = local_path.relative_to(img_root)
    except ValueError:
        rel = local_path
    return {
        "url": url,
        "local_path": str(rel).replace("\\", "/"),   # forward slashes everywhere
    }


# ── Parsing ───────────────────────────────────────────────────────────────────

def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def _img_url_from_tag(img_tag) -> str | None:
    """Extract image URL from common attributes used by lazy loaders."""
    if not img_tag:
        return None
    for attr in ("src", "data-src", "data-original", "data-lazy-src", "data-echo"):
        src = (img_tag.get(attr) or "").strip()
        if src and not src.startswith("data:"):
            return abs_url(src)
    return None


def extract_img_src(tag) -> str | None:
    """Return absolute src of first <img> inside tag, or None."""
    if not tag:
        return None
    img = tag.find("img")
    return _img_url_from_tag(img)


def extract_question_body_img_src(q_wrap) -> str | None:
    """Find a body diagram image URL from question wrapper, excluding choice images."""
    if not q_wrap:
        return None

    for img in q_wrap.find_all("img"):
        # Skip images that are part of answer choices.
        if img.find_parent(lambda t: t.name == "div" and "cho-item" in (t.get("class") or [])):
            continue
        src = _img_url_from_tag(img)
        if src:
            return src

    # Some pages lazy-load diagrams on non-img elements.
    for tag in q_wrap.find_all(True):
        if tag.find_parent(lambda t: t.name == "div" and "cho-item" in (t.get("class") or [])):
            continue

        for attr in ("data-src", "data-original", "data-lazy-src", "data-bg"):
            src = (tag.get(attr) or "").strip()
            if src and not src.startswith("data:"):
                return abs_url(src)

        style = tag.get("style") or ""
        m = re.search(r"background-image\s*:\s*url\((['\"]?)([^)\"']+)\1\)", style, re.I)
        if m:
            return abs_url(m.group(2).strip())
    return None


def extract_question_table_text(q_wrap) -> str:
    """Serialize question tables (outside choices) into compact text."""
    if not q_wrap:
        return ""

    tables = []
    for table in q_wrap.find_all("table"):
        if table.find_parent(lambda t: t.name == "div" and "cho-item" in (t.get("class") or [])):
            continue

        rows = []
        for tr in table.find_all("tr"):
            cells = [clean(td.get_text(" ", strip=True)) for td in tr.find_all(["th", "td"])]
            cells = [c for c in cells if c]
            if cells:
                rows.append(" | ".join(cells))

        if rows:
            tables.append(" ; ".join(rows))

    return " || ".join(tables)


def extract_csrf_magic_token(page_soup) -> str | None:
    """Extract csrfMagicToken value embedded in inline scripts."""
    if page_soup is None:
        return None
    for script in page_soup.find_all("script"):
        text = script.string or script.get_text() or ""
        m = re.search(r'var\s+csrfMagicToken\s*=\s*"([^"]+)"', text)
        if m:
            return m.group(1)
    return None


def fetch_correct_choice(
    *,
    qid: str,
    exam_slug: str,
    exam_url: str,
    csrf_token: str | None,
    answer_cache: dict,
    answer_state: dict,
) -> str | None:
    """
    Fetch official correct choice from Kehulum API.
    Returns letter A-E when available; otherwise None.
    """
    if not qid or not csrf_token or not answer_state.get("enabled", True):
        return None

    if qid in answer_cache:
        return answer_cache[qid]

    endpoint = f"{BASE_URL}/api/exam/get-answer"
    payload = {
        "qid": qid,
        "ans": "A",  # endpoint returns same key regardless of selected choice
        "keh_tokens": csrf_token,
        "exams": exam_slug,
        "subj": exam_slug,
        "pageno": "1",
        "dci": "1",
        "dco": "1",
    }
    headers = {
        "Referer": exam_url,
        "X-Requested-With": "XMLHttpRequest",
    }

    try:
        r = session.post(endpoint, data=payload, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError):
        return None

    html = str(data.get("b") or "")
    if "Answer Not Found" in html:
        answer_state["misses"] = answer_state.get("misses", 0) + 1
        # If first few questions have no official key, skip expensive lookups for this exam.
        if answer_state.get("hits", 0) == 0 and answer_state["misses"] >= 3:
            answer_state["enabled"] = False
        answer_cache[qid] = None
        return None

    letter = None
    m = re.search(r"Correct\s*Answer[^<]*<.*?>\s*\(([A-E])\)", html, re.I | re.S)
    if not m:
        m = re.search(r"\(([A-E])\)\s*</span>", html, re.I)
    if m:
        letter = m.group(1).upper()
        answer_state["hits"] = answer_state.get("hits", 0) + 1

    answer_cache[qid] = letter
    return letter


def parse_questions(
    page_soup,
    img_dir: Path,
    img_root: Path,
    *,
    exam_slug: str,
    exam_url: str,
    answer_cache: dict,
    answer_state: dict,
) -> list[dict]:
    """
    Parse all questions on one soup page.

    Each question dict:
    {
      "Number":         int,
      "Question":       str,
      "Question_image": { "url": ..., "local_path": ... } | null,
      "Choices": [
        { "letter": "A", "text": "...", "image": null },
        { "letter": "B", "text": null,  "image": { "url": ..., "local_path": ... } },
        ...
      ],
      "Correct_choice": str | null
    }
    """
    questions = []
    csrf_token = extract_csrf_magic_token(page_soup)
    q_tags = page_soup.find_all("h3", string=re.compile(r"^\s*Question\s+\d+\s*$", re.I))

    for h3 in q_tags:
        m = re.search(r"(\d+)", h3.get_text())
        if not m:
            continue
        q_num = int(m.group(1))

        choices = []
        choices_seen = set()
        correct = None

        # Current site layout: h3 sits in div.isQuestionNo, followed by div.question-border.
        head_wrap = h3.find_parent("div", class_=lambda c: c and "isQuestionNo" in c)
        q_wrap = None
        if head_wrap:
            q_wrap = head_wrap.find_next_sibling(
                lambda t: t.name == "div" and "question-border" in (t.get("class") or [])
            )

        if q_wrap is None:
            continue

        q_text_tag = q_wrap.select_one("div.isQuesion")
        q_text = clean(q_text_tag.get_text(" ", strip=True)) if q_text_tag else ""
        table_text = extract_question_table_text(q_wrap)
        if table_text:
            q_text = f"{q_text} Table: {table_text}" if q_text else f"Table: {table_text}"

        # Detect a shared choice preamble — text that sits between the question body
        # and the first choice div (e.g. "In group I it will be" for Q4 type questions).
        choice_preamble = ""
        first_cho = q_wrap.find("div", class_="cho-item")
        if q_text_tag and first_cho:
            past_question = False
            for el in q_wrap.children:
                if el is q_text_tag:
                    past_question = True
                    continue
                if el is first_cho:
                    break
                if past_question and hasattr(el, "get_text"):
                    # Skip table elements (already captured) and radio inputs.
                    if el.find("table") or el.find("input"):
                        continue
                    t = clean(el.get_text(" ", strip=True))
                    if t:
                        choice_preamble = (choice_preamble + " " + t).strip()

        # Question image (diagram in prompt body)
        body_img_url = extract_question_body_img_src(q_wrap)
        body_img_ok = False
        if body_img_url:
            fname = f"q{q_num}_body{ext_from_url(body_img_url)}"
            dest = img_dir / fname
            body_img_ok = download_image(body_img_url, dest)
            time.sleep(IMAGE_DELAY)

        # Choices
        qid = ""
        qid_input = q_wrap.select_one('input[type="radio"][name^="answer-"]')
        if qid_input:
            qid = (qid_input.get("name") or "").split("answer-")[-1]

        for item in q_wrap.select("div.cho-item"):
            letter_tag = item.select_one("span.choice-letter-lables")
            letter = clean(letter_tag.get_text()) if letter_tag else (item.get("ans") or "").upper()
            if letter not in CHOICE_LETTERS or letter in choices_seen:
                continue

            choices_seen.add(letter)

            # Best-effort correct answer extraction if page marks a choice.
            if any(cls for cls in (item.get("class") or []) if re.search(r"correct|right", cls, re.I)):
                correct = letter

            img_src = extract_img_src(item)
            if img_src:
                fname = f"q{q_num}_{letter}{ext_from_url(img_src)}"
                dest = img_dir / fname
                ok = download_image(img_src, dest)
                time.sleep(IMAGE_DELAY)
                choices.append({
                    "letter": letter,
                    "text": None,
                    "image": image_record(img_src, dest, img_root) if ok else {"url": img_src, "local_path": None},
                })
            else:
                raw = clean(item.get_text(" ", strip=True))
                # Remove the first standalone choice-letter token anywhere in the line,
                # preserving any prefix text that appears before the letter label.
                text_only = re.sub(rf"\b{re.escape(letter)}\b\s*", "", raw, count=1).strip()
                # Prepend shared preamble text if present (e.g. "In group I it will be").
                if choice_preamble:
                    text_only = f"{choice_preamble} {text_only}".strip()
                choices.append({
                    "letter": letter,
                    "text": text_only,
                    "image": None,
                })

        order = {l: i for i, l in enumerate("ABCDE")}
        choices.sort(key=lambda c: order.get(c["letter"], 99))

        # Prefer official answer API when available.
        api_correct = fetch_correct_choice(
            qid=qid,
            exam_slug=exam_slug,
            exam_url=exam_url,
            csrf_token=csrf_token,
            answer_cache=answer_cache,
            answer_state=answer_state,
        )
        if api_correct in CHOICE_LETTERS:
            correct = api_correct

        q_image = None
        if body_img_url:
            fname = f"q{q_num}_body{ext_from_url(body_img_url)}"
            dest = img_dir / fname
            q_image = image_record(body_img_url, dest, img_root) if body_img_ok else {"url": body_img_url, "local_path": None}

        questions.append({
            "Number": q_num,
            "Question": q_text,
            "Question_image": q_image,
            "Choices": choices,
            "Correct_choice": correct,
        })

    return questions


def get_max_page(page_soup, base_url) -> int:
    max_p = 1
    for a in page_soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(base_url):
            m = re.search(r"/(\d+)$", href[len(base_url):])
            if m:
                max_p = max(max_p, int(m.group(1)))
    return max_p


# ── Core scraper ─────────────────────────────────────────────────────────────

def scrape_exam(stream, year, subject, out_root: Path, max_questions: int | None = None) -> dict | None:
    name     = subject["name"]
    slug     = subject["slug"]
    base_url = f"{BASE_URL}/entrance-exam/{stream}-science/{year}/{slug}"

    # Image folder: images/natural_2016_physics/
    safe_name = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    img_dir   = out_root / "images" / f"{stream}_{year}_{safe_name}"
    img_dir.mkdir(parents=True, exist_ok=True)

    print(f"  → {name:40s}", end="", flush=True)

    page1 = get_soup(base_url)
    if page1 and is_not_found_page(page1):
        new_slug = resolve_subject_slug(stream, year, subject)
        if new_slug and new_slug != slug:
            slug = new_slug
            base_url = f"{BASE_URL}/entrance-exam/{stream}-science/{year}/{slug}"
            page1 = get_soup(base_url)

    if page1 is None:
        print(" [FAILED]")
        return None

    if is_not_found_page(page1):
        print(" [NOT FOUND]")
        return None

    answer_cache = {}
    answer_state = {"enabled": True, "hits": 0, "misses": 0}

    all_qs   = parse_questions(
        page1,
        img_dir,
        out_root,
        exam_slug=slug,
        exam_url=base_url,
        answer_cache=answer_cache,
        answer_state=answer_state,
    )
    max_page = get_max_page(page1, base_url)
    time.sleep(PAGE_DELAY)

    for page in range(2, max_page + 1):
        page_url = f"{base_url}/{page}"
        pg = get_soup(page_url)
        if pg:
            all_qs.extend(
                parse_questions(
                    pg,
                    img_dir,
                    out_root,
                    exam_slug=slug,
                    exam_url=page_url,
                    answer_cache=answer_cache,
                    answer_state=answer_state,
                )
            )
        time.sleep(PAGE_DELAY)

    if max_questions is not None and max_questions > 0 and len(all_qs) > max_questions:
        all_qs = all_qs[:max_questions]

    n_img_q  = sum(1 for q in all_qs if q["Question_image"] or
                   any(c["image"] for c in q["Choices"]))
    print(f" {len(all_qs):3d} questions  ({n_img_q} with images, {max_page} pages)")

    return {
        "Subject":   name,
        "Year":      year,
        "Stream":    stream,
        "_meta": {
            "slug":           slug,
            "url":            base_url,
            "question_count": len(all_qs),
            "image_dir":      str(img_dir.relative_to(out_root)).replace("\\", "/"),
            "scraped_at":     datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
        "Questions": all_qs,
    }


# ── Output ────────────────────────────────────────────────────────────────────

def save_json(exams: list, path: Path):
    output = [{k: v for k, v in e.items() if k != "_meta"} for e in exams]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n[JSON] Saved → {path}")


def save_csv(exams: list, path: Path):
    """Flat CSV — one row per question. Image columns hold the local_path."""
    rows = []
    for exam in exams:
        for q in exam.get("Questions", []):
            # Flatten choices into lettered columns
            cd_text  = {}
            cd_image = {}
            for c in q.get("Choices", []):
                l = c["letter"]
                cd_text[l]  = c.get("text") or ""
                cd_image[l] = (c.get("image") or {}).get("local_path") or ""

            q_img = q.get("Question_image") or {}
            rows.append({
                "Subject":          exam["Subject"],
                "Year":             exam["Year"],
                "Stream":           exam["Stream"],
                "Number":           q["Number"],
                "Question":         q["Question"],
                "Question_image":   q_img.get("local_path", ""),
                "A_text":           cd_text.get("A", ""),
                "A_image":          cd_image.get("A", ""),
                "B_text":           cd_text.get("B", ""),
                "B_image":          cd_image.get("B", ""),
                "C_text":           cd_text.get("C", ""),
                "C_image":          cd_image.get("C", ""),
                "D_text":           cd_text.get("D", ""),
                "D_image":          cd_image.get("D", ""),
                "E_text":           cd_text.get("E", ""),
                "E_image":          cd_image.get("E", ""),
                "Correct_choice":   q.get("Correct_choice") or "",
            })

    if not rows:
        print("[CSV]  No data to write.")
        return

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[CSV]  Saved → {path}  ({len(rows)} rows)")


# ── Runner ────────────────────────────────────────────────────────────────────

def run(streams=None, years=None, subject_filter=None,
    out_dir="euee_output", do_csv=True, max_questions=None):

    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    streams   = streams or list(SUBJECTS.keys())
    all_exams = []
    total_q   = 0

    for stream in streams:
        target_years = years or list(SUBJECTS[stream].keys())
        for year in target_years:
            subjects = SUBJECTS[stream].get(year, [])
            if not subjects:
                print(f"[WARN] No subjects catalogued for {stream}/{year}")
                continue

            if subject_filter:
                subjects = [
                    s for s in subjects
                    if subject_filter.lower() in s["name"].lower()
                    or subject_filter.lower() in s["slug"]
                ]

            print(f"\n── {stream.upper()} SCIENCE  {year} E.C ──")
            for subj in subjects:
                result = scrape_exam(stream, year, subj, out_root, max_questions=max_questions)
                if result:
                    all_exams.append(result)
                    total_q += result["_meta"]["question_count"]

    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_root / f"euee_{ts}.json"
    save_json(all_exams, json_path)

    if do_csv:
        save_csv(all_exams, out_root / f"euee_{ts}.csv")

    print(f"\n{'═'*54}")
    print(f"  Total questions  : {total_q}")
    print(f"  Total exams      : {len(all_exams)}")
    print(f"  Output directory : {out_root.resolve()}")
    print(f"{'═'*54}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Kehulum EUEE Scraper (with image download)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--stream",  choices=["natural", "social"],
                        help="Stream to scrape (default: both)")
    parser.add_argument("--year",    help="E.C year, e.g. 2016 (default: all)")
    parser.add_argument("--subject", help="Subject filter, e.g. physics")
    parser.add_argument("--out",     default="euee_output",
                        help="Output directory (default: euee_output/)")
    parser.add_argument("--no-csv",  action="store_true",
                        help="Skip CSV export")
    parser.add_argument("--max-questions", type=int,
                        help="Maximum questions per exam to keep (e.g. 50)")
    args = parser.parse_args()

    run(
        streams        = [args.stream] if args.stream else None,
        years          = [args.year]   if args.year   else None,
        subject_filter = args.subject,
        out_dir        = args.out,
        do_csv         = not args.no_csv,
        max_questions  = args.max_questions,
    )


if __name__ == "__main__":
    main()
