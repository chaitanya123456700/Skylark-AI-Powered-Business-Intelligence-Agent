import re
from dateutil import parser as dateparser

NULL_TOKENS = {"", "n/a", "na", "null", "none", "-", "--", "tbd", "unknown", "?", "nil"}


def clean_null(value):
    """Collapse all the ways messy spreadsheets spell 'missing' into a real None."""
    if value is None:
        return None
    v = str(value).strip()
    if v.lower() in NULL_TOKENS:
        return None
    return v


def normalize_date(raw_value):
    v = clean_null(raw_value)
    if v is None:
        return None
    try:
        dt = dateparser.parse(v, fuzzy=True)
        return dt.date().isoformat()
    except (ValueError, OverflowError, TypeError):
        return None


def normalize_number(raw_value):
    v = clean_null(raw_value)
    if v is None:
        return None
    # strip currency symbols, commas, stray whitespace, percent signs
    v = re.sub(r"[^\d.\-]", "", v)
    if v in ("", "-", ".", "-."):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def normalize_text(raw_value, synonym_map: dict | None = None):
    v = clean_null(raw_value)
    if v is None:
        return None
    v = re.sub(r"\s+", " ", v).strip()
    key = v.lower()
    if synonym_map and key in synonym_map:
        return synonym_map[key]
    # Title-case values that came in ALL CAPS or all lowercase; leave mixed-case as-is
    # (mixed case is usually already a proper name, e.g. a client name).
    if v.isupper() or v.islower():
        return v.title()
    return v
