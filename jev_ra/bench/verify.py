"""Outcome predicates. A run that finishes fast without doing the task is a failure, not a time."""

import re

# Google Flights answers in the browser's locale, so every signal has to be language-agnostic.
DURATION = re.compile(r"\b\d{1,2}\s*hr\b|\b\d{1,2}\s*h\s*\d{1,2}\b|\d{1,2}\s*시간", re.IGNORECASE)
PRICE = re.compile(r"[$€£₩]\s?\d|\d[\d,]*\s?(?:USD|EUR|CHF|GBP|KRW|원)")
ORIGIN = re.compile(r"\bZRH\b|Z(?:u|ü)rich|취리히", re.IGNORECASE)
DESTINATION = re.compile(r"\b(?:LON|LHR|LGW|STN|LTN|LCY)\b|London|런던", re.IGNORECASE)
DEPARTURE = re.compile(r"2026-09-20|\b(?:Sep(?:tember)?)\s*20\b|9월\s*20일")
ACTIVE = {"true", "page", "step", "location", "date", "time", "on"}


def text_of(row):
    """The page text a predicate should read, never None."""
    return row.get("text") or ""


def url_of(row):
    """The final url a predicate should read, never None."""
    return row.get("url") or ""


def wikipedia(row):
    """The article itself is open, not a search result that mentions it."""
    url = url_of(row).lower()
    return "incompleteness" in url and "search" not in url


def flights(row):
    """A submitted one-way search for the right route and date, with results on screen."""
    url = url_of(row)
    text = text_of(row)
    if "travel/flights" not in url or "tfs=" not in url:
        return False
    return all(
        pattern.search(text) for pattern in (ORIGIN, DESTINATION, DEPARTURE, DURATION, PRICE)
    )


def oliveyoung_sort(row):
    """The newest-first sort is applied, by url or by the active tab."""
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
    return any("2023" in (result.get("text") or "") and result.get("url") for result in row.get("results") or [])


def form_fill(row):
    """The confirmation page carries every value that was typed."""
    text = text_of(row)
    return "Order confirmed" in text and "Ada Lovelace" in text and "Express" in text
