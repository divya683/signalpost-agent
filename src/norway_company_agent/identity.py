from __future__ import annotations

import re
import unicodedata
import urllib.parse
from typing import Any


LEGAL_AND_GENERIC = {
    "as", "asa", "ans", "da", "enk", "iks", "sa", "sam", "sti", "stiftelsen",
    "nuf", "ab", "b", "v", "limited", "ltd", "inc", "plc", "the", "og", "and",
}

# Words that mark a name as a parent/holding/brand umbrella rather than the
# operating company itself. Used only to decide whether a site that matched on
# weak evidence should be trusted to speak for this specific legal entity.
GROUP_WORDS = {
    "group", "gruppen", "gruppe", "konsern", "konsernet", "holding", "holdings",
    "invest", "eiendom", "partners", "kjeden", "kjede",
}


def _tokens(value: Any) -> list[str]:
    text = str(value or "").translate(str.maketrans({"ø": "o", "Ø": "O", "å": "a", "Å": "A", "æ": "ae", "Æ": "AE"}))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    return [token for token in re.findall(r"[a-z0-9]+", text) if token not in LEGAL_AND_GENERIC and len(token) > 1]


def _structured_names(value: Any) -> list[str]:
    names: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"name", "legalName", "alternateName"} and isinstance(child, str):
                names.append(child)
            else:
                names.extend(_structured_names(child))
    elif isinstance(value, list):
        for child in value:
            names.extend(_structured_names(child))
    return names


def assess_website_identity(profile: dict[str, Any]) -> dict[str, Any]:
    website = profile.get("evidence", {}).get("website", {})
    value = website.get("value") or {}
    core = _tokens(profile.get("name"))
    hostname = urllib.parse.urlparse(value.get("final_url") or website.get("source_url") or "").hostname or ""
    structured_names = _structured_names(value.get("structured_organisations") or [])
    rendered = value.get("js_fallback") or {}
    homepage_identity_parts = [
        value.get("title"), value.get("description"), value.get("identity_text_excerpt"), hostname, *structured_names,
        rendered.get("title"),
    ]
    candidate_parts = [
        *homepage_identity_parts, value.get("main_text_excerpt"),
        *[page.get("title") for page in value.get("pages", [])],
        *[page.get("main_text_excerpt") for page in value.get("pages", [])],
        *[page.get("identity_text_excerpt") for page in value.get("pages", [])],
    ]
    candidate_parts.append(rendered.get("main_text_excerpt"))
    candidate_text = " ".join(str(part or "") for part in candidate_parts)
    homepage_candidate_text = " ".join(str(part or "") for part in [*homepage_identity_parts, value.get("main_text_excerpt"), rendered.get("main_text_excerpt")])
    normalized_candidate_text = " ".join(_tokens(candidate_text))
    candidate_tokens = set(_tokens(candidate_text))
    org_digits = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    compact_candidate = re.sub(r"\D", "", candidate_text)
    compact_homepage_candidate = re.sub(r"\D", "", homepage_candidate_text)
    overlap = sorted(set(core) & candidate_tokens)
    ratio = len(overlap) / len(set(core)) if core else 0.0
    reasons = []
    parked_markers = (
        "domain is for sale", "domain for sale", "hugedomains", "parked at", "miss hosting",
        "her flytter snart en ny gjest", "has been informing visitors",
        "find the best information and most relevant links on all topics related to",
    )
    normalized_raw = unicodedata.normalize("NFKD", candidate_text).encode("ascii", "ignore").decode().casefold()
    homepage_token_sets = [set(_tokens(part)) for part in homepage_identity_parts if part]
    exact_homepage_name = bool(core and any(set(core).issubset(tokens) for tokens in homepage_token_sets))
    substantive_homepage = len(str(value.get("main_text_excerpt") or "").strip()) >= 100
    is_business_sports_club = bool(re.search(r"(?:^|\s)B\.?\s*I\.?\s*L\.?(?:\s|$)", str(profile.get("name") or ""), re.I))
    if any(marker in normalized_raw for marker in parked_markers):
        score = 0.1
        reasons.append("captured page is a parked, for-sale, or generic hosting placeholder")
    elif is_business_sports_club and "bedriftsidrett" not in normalized_candidate_text and "b i l" not in normalized_candidate_text:
        score = 0.3
        reasons.append("business sports-club entity points to the operating company's site without club evidence")
    elif org_digits and org_digits in compact_homepage_candidate:
        score = 1.0
        reasons.append("exact organisation number appears in homepage identity evidence")
    elif len(core) >= 2 and exact_homepage_name:
        score = 0.95
        reasons.append("all normalized legal-name tokens appear together in homepage identity evidence")
    elif len(core) == 1 and exact_homepage_name and substantive_homepage:
        score = 0.95
        reasons.append("single distinctive legal-name token appears in homepage identity evidence with substantive content")
    elif ratio >= 0.75 and len(overlap) >= 2:
        score = 0.85
        reasons.append("most legal-name tokens appear, but exact identity is incomplete")
    elif ratio >= 0.5 and len(overlap) >= 2:
        score = 0.65
        reasons.append("partial legal-name overlap only")
    else:
        score = 0.3
        reasons.append("registry-linked URL lacks strong exact-entity identity evidence")
    status = "exact" if score >= 0.9 else "review" if score >= 0.8 else "related_or_uncertain"

    # Ownership is a stricter, separate question from "is this page about this
    # company". A registry-listed domain is frequently the parent group's or a
    # shared brand site, which mentions the subsidiary without belonging to it.
    # Anything derived from the page body (social accounts, news posts, job
    # ads) speaks for whoever owns the site, so those require this check, not
    # the looser status above.
    registered_domain = str(value.get("registered_domain") or "")
    # Domains run words together and often extend them ("sesamist.com" for
    # Sesam), so a name token counts as domain-backed when it appears inside
    # the domain label, not only when it equals a whole label.
    # Matching runs both directions: a domain may extend the name
    # ("sesamist.com" for Sesam), and a registered name may glue its legal form
    # onto the distinctive part ("RAFTOSTIFTELSEN" on rafto.no).
    domain_label = "".join(_tokens(registered_domain.split(".")[0] if registered_domain else hostname.split(".")[0]))
    domain_backed_tokens = {
        token for token in core
        if token in domain_label or (len(domain_label) >= 4 and domain_label in token)
    }
    other_org_numbers = sorted(
        found for found in set(re.findall(r"(?<!\d)(\d{9})(?!\d)", re.sub(r"(?<=\d)[ .](?=\d)", "", homepage_candidate_text)))
        if found != org_digits
    )
    structured_token_sets = [set(_tokens(name)) for name in structured_names if name]
    structured_names_this_company = bool(core and any(set(core).issubset(tokens) for tokens in structured_token_sets))
    structured_names_other_entity = bool(
        structured_token_sets
        and not structured_names_this_company
        and any(tokens and tokens & GROUP_WORDS for tokens in structured_token_sets)
    )
    # The page title is the strongest ownership slot a site has: an operating
    # company's own site titles itself with its own name, while a property
    # manager, accountant, web agency, or franchise brand titles itself with
    # theirs and never with the client's. This is what separates a legitimate
    # acronym domain (rs.no titled "Redningsselskapet") from a manager's domain
    # (usbl.no titled "Boligbyggelag, forretningsfører og bolig").
    title_tokens = set(_tokens(value.get("title")))
    exact_name_in_title = bool(core and set(core).issubset(title_tokens))

    group_site_signals = []
    if structured_names_other_entity:
        group_site_signals.append("page's structured organisation name is a group/holding entity, not this company")
    if other_org_numbers and org_digits not in compact_homepage_candidate:
        group_site_signals.append("page shows a different organisation number and not this company's")
    if core and domain_label and not domain_backed_tokens and not exact_name_in_title and len(overlap) <= 1:
        group_site_signals.append("domain name is unrelated to the legal name and only one name token matched")

    if org_digits and org_digits in compact_homepage_candidate:
        own_site_confirmed, ownership_basis = True, "exact organisation number present on the site"
    elif len(core) >= 2 and exact_homepage_name and not group_site_signals:
        own_site_confirmed, ownership_basis = True, "full legal name present on the site with no group-site signals"
    elif core and exact_homepage_name and domain_backed_tokens and not group_site_signals:
        own_site_confirmed, ownership_basis = True, "legal name present and the registered domain carries that name"
    elif core and exact_name_in_title and not group_site_signals:
        own_site_confirmed, ownership_basis = True, "site titles itself with this company's full legal name"
    else:
        own_site_confirmed = False
        ownership_basis = (
            "group/parent/brand-site signals present" if group_site_signals
            else "no organisation number and no domain-backed exact name on the site"
        )

    return {
        "status": status,
        "score": score,
        "publishable": status == "exact",
        "own_site_confirmed": own_site_confirmed,
        "ownership_basis": ownership_basis,
        "group_site_signals": group_site_signals,
        "other_organisation_numbers_on_page": other_org_numbers[:5],
        "legal_name_tokens": core,
        "matched_tokens": overlap,
        "reasons": reasons,
        "method": "deterministic_name_org_evidence_v3",
    }


# Accounts belonging to the website's builder, CMS, theme vendor, or the agency
# that made the site. A footer link to one of these is never the company's own
# account, however well the rest of the page matches.
VENDOR_HANDLE_WORDS = {
    "wix", "wixcom", "squarespace", "wordpress", "wpengine", "shopify", "webflow",
    "godaddy", "hostinger", "onecom", "domeneshop", "idium", "wpbakery", "elementor",
    "divi", "woocommerce", "joomla", "drupal", "typo", "umbraco", "sharepoint",
    "mailchimp", "hubspot", "squareup", "webnode", "jimdo", "strikingly",
}
# Non-profile destinations: share widgets, login walls, and platform plumbing.
NON_PROFILE_PATH = re.compile(
    r"/(?:sharer|share|share\.php|intent|login|signup|signin|register|plugins|dialog|"
    r"tr\b|privacy|terms|help|about|legal|policies|home|explore|hashtag|search|"
    r"results|watch|embed|player|oembed)(?:/|$|\.|\?)",
    re.I,
)


def assess_social_identity(profile: dict[str, Any], link: dict[str, str]) -> dict[str, Any]:
    core = _tokens(profile.get("name"))
    parsed = urllib.parse.urlparse(link.get("url") or "")
    handle_text = urllib.parse.unquote(parsed.path)
    handle_tokens = set(_tokens(handle_text))
    handle_compact = "".join(_tokens(handle_text))
    matched = [token for token in core if token in handle_compact]
    core_compact = "".join(core)
    ratio = len(set(matched)) / len(set(core)) if core else 0.0

    # Structural disqualifiers are checked before any name scoring, because a
    # share widget or a theme vendor's account can still contain the company
    # name in a query string and would otherwise score well.
    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        return {
            **link, "identity_score": 0.0, "publishable": False, "matched_tokens": [],
            "reason": "link points at the platform root, not a company profile",
            "method": "deterministic_social_handle_identity_v2",
        }
    if NON_PROFILE_PATH.search(parsed.path):
        return {
            **link, "identity_score": 0.0, "publishable": False, "matched_tokens": [],
            "reason": "link is a share widget, login wall, or platform utility page, not a profile",
            "method": "deterministic_social_handle_identity_v2",
        }
    if handle_tokens & VENDOR_HANDLE_WORDS:
        return {
            **link, "identity_score": 0.0, "publishable": False, "matched_tokens": [],
            "reason": "handle belongs to the site builder, CMS, theme, or web agency",
            "method": "deterministic_social_handle_identity_v2",
        }
    # A group/holding handle cannot stand in for an operating subsidiary unless
    # the company's own registered name carries the same umbrella word. Handles
    # are usually run together ("havelektrogruppen"), so this is a substring
    # test rather than a token test.
    umbrella_in_handle = any(word in handle_compact for word in GROUP_WORDS)
    umbrella_in_company = any(word in core_compact for word in GROUP_WORDS)
    if umbrella_in_handle and not umbrella_in_company:
        return {
            **link, "identity_score": 0.3, "publishable": False, "matched_tokens": matched,
            "reason": "handle names a group/holding umbrella while this company does not",
            "method": "deterministic_social_handle_identity_v2",
        }

    if core_compact and core_compact in handle_compact:
        score = 0.98
        reason = "normalized legal-name sequence appears in the social handle"
    elif len(core) == 1 and matched:
        score = 0.95
        reason = "single distinctive legal-name token appears in the social handle"
    elif ratio >= 0.75 and len(set(matched)) >= 2:
        score = 0.9
        reason = "most legal-name tokens appear in the social handle"
    else:
        score = 0.3
        reason = "social handle lacks strong exact-entity name evidence"
    return {
        **link,
        "identity_score": score,
        "publishable": score >= 0.9,
        "matched_tokens": matched,
        "reason": reason,
        "method": "deterministic_social_handle_identity_v2",
    }


def apply_website_identity_gate(profile: dict[str, Any], website: dict[str, Any]) -> dict[str, Any]:
    if website.get("status") != "available":
        return {"website": website, "assessment": None, "quarantined_social_links": 0}
    temporary_profile = {**profile, "evidence": {**profile.get("evidence", {}), "website": website}}
    value = website.get("value") or {}
    assessment = assess_website_identity(temporary_profile)
    value["identity_assessment"] = assessment
    original = list(value.get("discovered_social_links") or value.get("social_links") or [])
    value["discovered_social_links"] = original
    social_assessments = [assess_social_identity(profile, link) for link in original]
    value["social_link_assessments"] = social_assessments
    # Social accounts are read out of the site body, so they belong to whoever
    # owns the site. Publishing them requires confirmed ownership, not just a
    # page that mentions this company.
    value["social_links"] = [
        {"platform": item["platform"], "url": item["url"]}
        for item in social_assessments
        if assessment["publishable"] and assessment["own_site_confirmed"] and item["publishable"]
    ]
    website["value"] = value
    return {
        "website": website,
        "assessment": assessment,
        "quarantined_social_links": len(original) - len(value["social_links"]),
    }
