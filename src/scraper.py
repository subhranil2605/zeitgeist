import re

import requests
from bs4 import BeautifulSoup

TRENDING_URL = "https://github.com/trending/{language}?since=daily"
USER_AGENT = "github-trending-digest/1.0 (personal project, 1 request/day)"


def fetch_trending(language: str) -> list[dict]:
    """Return one dict per repo row on today's trending page.

    Fields that couldn't be parsed are left as None. This function doesn't
    judge whether the result is "good enough" - that's check_parse_quality's
    job, called separately by the caller.
    """

    resp = requests.get(
        TRENDING_URL.format(language=language),
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )

    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    return [_parse_row(row) for row in soup.select("article.Box-row")]


def _parse_row(row) -> dict:
    full_name = None
    description = None
    language = None
    stars_total = None
    stars_today = None

    # Scrape the data
    repo_title = row.select(".h3.lh-condensed")[0]
    title_link = repo_title.find("a", class_="Link")
    desc_tag = row.select_one(".col-9.color-fg-muted.my-1.tmp-pr-4")
    lang_tag = row.select_one("[itemprop='programmingLanguage']")
    stars_tag, _ = row.select(".tmp-mr-3.Link.Link--muted.d-inline-block")
    today_tag = row.select_one(".float-sm-right")

    if title_link:
        full_name = title_link.get("href").strip("/")

    if desc_tag:
        description = desc_tag.get_text(strip=True)

    if lang_tag:
        language = lang_tag.get_text(strip=True)

    if stars_tag:
        stars_total = _parse_int(stars_tag.get_text(strip=True))

    if today_tag:
        stars_today = _parse_int(today_tag.get_text(strip=True))

    # Build the output
    result = {
        "full_name": full_name,
        "description": description,
        "language": language,
        "stars_total": stars_total,
        "stars_today": stars_today,
        "url": f"https://githuc.com/{full_name}" if full_name else None,
    }

    return result


def _parse_int(text: str) -> int | None:
    match = re.search(r"[\d,]+", text)
    return int(match.group().replace(",", "")) if match else None


def check_parse_quality(repos: list[dict], max_missing_ratio: float = 0.2) -> bool:
    """Structure-check guard.

    Returns False if too many required fields came back empty, which most
    likely means Github changed the page's HTML structure rather than that
    a few repos individually lack descriptions. False means: abort the run,
    don't send a broken digest.
    """
    if not repos:
        return False

    required = ("full_name", "description", "stars_total")
    missing = sum(1 for r in repos for field in required if r.get(field) is None)
    total_checks = len(repos) * len(required)
    return (missing / total_checks) <= max_missing_ratio
