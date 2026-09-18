"""Outcome predicates. A run that finishes fast without doing the task is a failure, not a time."""

import re

DURATION = re.compile(r"\b\d{1,2}\s*hr\b|\b\d{1,2}\s*h\s*\d{1,2}\b", re.IGNORECASE)
PRICE = re.compile(r"[$€£₩]\s?\d|\d[\d,]*\s?(?:USD|EUR|CHF|GBP|KRW|원)")
ACTIVE = {"true", "page", "step", "location", "date", "time", "on"}


def text_of(row):
    return row.get("text") or ""


def url_of(row):
    return row.get("url") or ""


def wikipedia(row):
    """The article itself is open, not a search result that mentions it."""
    url = url_of(row).lower()
    return "incompleteness" in url and "search" not in url


def flights(row):
    url = url_of(row)
    text = text_of(row)
    if "travel/flights" not in url or "tfs=" not in url:
        return False
    origin = "Zurich" in text or "ZRH" in text
    destination = "London" in text or "LON" in text or "LHR" in text or "LGW" in text
    dated = bool(re.search(r"\b(20|Sep|September)[^\n]{0,12}2026\b|2026-09-20", text))
    return origin and destination and dated and bool(DURATION.search(text)) and bool(PRICE.search(text))


def oliveyoung_sort(row):
    if "prdSort=02" in url_of(row):
        return True
    for element in row.get("elements") or []:
        if "신상품순" not in (element.get("label") or ""):
            continue
        for key in ("selected", "checked", "expanded"):
            if str(element.get(key, "")).lower() in ACTIVE:
                return True
    return False


def search_fact(row):
    """A year and a page to cite it from."""
    for result in row.get("results") or []:
        if "2023" in (result.get("text") or "") and result.get("url"):
            return True
    return False


def form_fill(row):
    text = text_of(row)
    return "Order confirmed" in text and "Ada Lovelace" in text and "Express" in text
