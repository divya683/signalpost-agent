"""Rules that decide whether a captured page is a real dated news post or a
single job advert for one specific company.

A URL under /news/ or /karriere/ proves nothing on its own. An archive index, a
"see more news" navigation label, a product page, a careers landing page, a
search link into the national job portal, and a parent company's vacancy list
all live at paths like those, and none of them is a publishable item for the
company being profiled. These checks exist to reject those.

The date rule deserves saying plainly: a "modified" or feed "updated" stamp is
not a publication date. A CMS rewrites dateModified when a template changes,
so accepting it would date a 2015 post to today. Only a genuine published
date counts, and an item without one is dropped rather than guessed at.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

# Navigation and call-to-action labels that a crawler picks up as a page title
# when it captures an index rather than an article.
MENU_LABELS = {
    "news", "nyheter", "aktuelt", "presse", "press", "pressemeldinger", "blogg", "blog",
    "artikler", "articles", "se mer", "se mer nyheter", "les mer", "les flere",
    "flere nyheter", "alle nyheter", "see more", "see more news", "all news",
    "latest news", "siste nytt", "nyhetsarkiv", "news archive", "archive", "arkiv",
    "media", "mediesenter", "newsroom", "nyhetsrom", "home", "hjem", "forside",
}
# Paths that are category or commerce pages rather than editorial posts.
NON_ARTICLE_PATH = re.compile(
    r"/(?:product|products|produkt|produkter|shop|butikk|nettbutikk|cart|handlekorg|"
    r"category|kategori|tag|emne|author|forfatter|page|side|search|sok|soek)(?:/|$)",
    re.I,
)
NEWS_SECTION = re.compile(r"/(?:news|press|presse|aktuelt|nyheter|artikler|articles|blog|blogg)(?:/|$)", re.I)

JOB_SECTION = re.compile(
    r"/(?:karriere|karriere-og-jobb|jobb|jobber|stilling|stillinger|ledige-stillinger|"
    r"vacancies|vacancy|careers|career|jobs|job|recruitment|rekruttering)(?:/|$)",
    re.I,
)
# Landing/overview labels for a careers section, as opposed to one advert.
JOB_LANDING_LABELS = {
    "karriere", "jobb", "jobber", "stilling", "stillinger", "ledige stillinger",
    "ledige jobber", "careers", "career", "jobs", "job", "vacancies", "vacancy",
    "work with us", "jobb hos oss", "bli en av oss", "join us", "open positions",
    "apply", "søk", "sok", "recruitment", "rekruttering", "our people", "people",
}
# Pages that live inside a careers section without being an advert.
CAREER_SUBPAGE_LABELS = {
    "contacts", "global contacts", "contact", "kontakt", "benefits", "fordeler",
    "culture", "kultur", "process", "prosess", "faq", "students", "studenter",
    "graduates", "trainee", "internship", "praktikant", "why us", "hvorfor oss",
    "about us", "om oss", "our values", "verdier", "life at", "meet us",
    "recruitment process", "rekrutteringsprosess", "summer job", "sommerjobb",
    "open application", "apne soknad", "spontaneous application",
}
# The national job portal. A link into its search results is a query, not an ad.
NAV_PORTAL_HOSTS = {"arbeidsplassen.nav.no", "nav.no", "www.nav.no"}
SEARCH_QUERY_KEYS = {"q", "query", "search", "sok", "soek", "keyword", "keywords", "fritekst"}


LEGAL_FORM_WORDS = {
    "as", "asa", "ans", "da", "enk", "iks", "sa", "sam", "sti", "nuf",
    "ab", "ltd", "limited", "inc", "plc", "og", "and", "the",
}


def _distinctive_tokens(value: Any) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if token not in LEGAL_FORM_WORDS and len(token) > 1
    }


def _slug_parts(url: str) -> list[str]:
    return [part for part in urlparse(str(url or "")).path.split("/") if part]


def _normalize_label(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    return text.rstrip(" .:|-–—")


def _looks_like_slug(part: str) -> bool:
    """A real article/advert slug carries words or an id, not just a section name."""
    cleaned = part.casefold()
    if re.fullmatch(r"\d{4}", cleaned) or re.fullmatch(r"\d{1,2}", cleaned):
        return False  # a year or month segment in a date-based archive path
    if _normalize_label(cleaned.replace("-", " ").replace("_", " ")) in MENU_LABELS:
        return False
    return bool(re.search(r"[a-z]{3}", cleaned) and ("-" in cleaned or "_" in cleaned or len(cleaned) >= 12)) or bool(re.search(r"\d{4,}", cleaned))


def parse_published_date(candidates: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (iso_date, basis) using only genuine publication fields.

    `candidates` carries whatever the crawler found. Modified/updated values are
    accepted as input and deliberately ignored, so the caller can record that it
    saw them without letting them stand in for a publish date.
    """
    for key in ("datePublished", "article:published_time", "published_time", "pubDate", "datetime", "dateCreated"):
        value = candidates.get(key)
        parsed = _coerce_date(value)
        if parsed:
            return parsed, f"publication date from {key}"
    return None, None


def _coerce_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        try:
            parsed = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    else:
        match = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
        if not match:
            return None
        try:
            parsed = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        except ValueError:
            return None
    if not 1990 <= parsed.year <= datetime.now(timezone.utc).year + 1:
        return None
    return parsed.isoformat()


def validate_news_item(page: dict[str, Any]) -> dict[str, Any]:
    """Decide whether one captured page is a real, dated news post."""
    url = str(page.get("url") or "")
    parts = _slug_parts(url)
    title = _normalize_label(page.get("title"))
    reasons: list[str] = []

    if not url.startswith(("http://", "https://")):
        reasons.append("not an absolute http(s) URL")
    if not NEWS_SECTION.search(urlparse(url).path):
        reasons.append("URL is not under a news or press section")
    if NON_ARTICLE_PATH.search(urlparse(url).path):
        reasons.append("URL is a product, category, tag, or search page, not an editorial post")
    if title in MENU_LABELS:
        reasons.append("title is a navigation or archive label, not a headline")
    if not title:
        reasons.append("no title captured")
    if not any(_looks_like_slug(part) for part in parts):
        reasons.append("URL has no article slug, so it is a section index rather than one post")

    published_at, basis = parse_published_date(page.get("date_candidates") or {})
    saw_modified_only = bool(
        not published_at
        and {key for key in (page.get("date_candidates") or {}) if "modif" in key.lower() or "updat" in key.lower()}
    )
    if not published_at:
        reasons.append(
            "only a modified/updated timestamp was available, which is not a publication date"
            if saw_modified_only else "no publication date found on the page"
        )

    return {
        "publishable": not reasons,
        "published_at": published_at,
        "date_basis": basis,
        "modified_only_date_rejected": saw_modified_only,
        "reasons": reasons,
        "method": "company_site_news_item_rules_v1",
    }


def validate_job_ad(page: dict[str, Any], *, own_site_host: str | None = None, company_name: str | None = None) -> dict[str, Any]:
    """Decide whether one captured page is a single job advert for this company."""
    url = str(page.get("url") or "")
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    parts = _slug_parts(url)
    title = _normalize_label(page.get("title"))
    reasons: list[str] = []

    if not url.startswith(("http://", "https://")):
        reasons.append("not an absolute http(s) URL")
    if host in NAV_PORTAL_HOSTS or any(part in NAV_PORTAL_HOSTS for part in [host]):
        query_keys = {key.casefold() for key in parse_qs(parsed.query)}
        if query_keys & SEARCH_QUERY_KEYS or not any(re.search(r"\d{4,}", part) for part in parts):
            reasons.append("link is a search into the national job portal, not one advert")
    if not JOB_SECTION.search(parsed.path) and not re.search(r"\d{5,}", parsed.path):
        reasons.append("URL is not under a jobs section and carries no advert id")
    if title in JOB_LANDING_LABELS:
        reasons.append("title is a careers landing or overview label, not one advert")
    if not title:
        reasons.append("no title captured")
    if not any(_looks_like_slug(part) for part in parts):
        reasons.append("URL has no advert slug or id, so it is a careers landing page")
    if own_site_host and host and host != own_site_host.casefold().removeprefix("www."):
        reasons.append("advert is hosted off the company's own confirmed domain")
    if any(_normalize_label(part.replace("-", " ").replace("_", " ")) in CAREER_SUBPAGE_LABELS for part in parts):
        reasons.append("URL is a careers section subpage (contacts, benefits, process) rather than an advert")

    # A slug alone is not evidence of an advert: a careers section's own
    # subpages carry slugs too. Require a positive advert marker, which is
    # either schema.org JobPosting markup (what search engines require to index
    # an advert) or a numeric advert id in the URL.
    markup = page.get("job_posting") or {}
    advert_id_in_url = bool(re.search(r"\d{4,}", parsed.path))
    if not markup and not advert_id_in_url:
        reasons.append("no JobPosting markup and no advert id, so this is not demonstrably one advert")

    # The employer named in the advert must be this company, so a parent's
    # vacancy republished on a shared careers site does not count.
    employer = page.get("employer_name") or markup.get("employer_name")
    if employer and company_name:
        # Legal-form suffixes are shared by most Norwegian companies, so they
        # are stripped before comparing. Leaving "AS" in would make every
        # employer look like a match.
        employer_tokens = _distinctive_tokens(employer)
        company_tokens = _distinctive_tokens(company_name)
        if company_tokens and not (company_tokens & employer_tokens):
            reasons.append("advert names a different employer than this company")

    return {
        "publishable": not reasons,
        "reasons": reasons,
        "method": "company_site_job_ad_rules_v1",
    }
