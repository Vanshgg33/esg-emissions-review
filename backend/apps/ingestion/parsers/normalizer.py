"""
Shared header normalisation utilities for ESG ingestion parsers.

Enterprise CSV exports use wildly inconsistent column naming — snake_case,
Title Case, spaces, abbreviations, and locale variants all appear in the wild.
This module provides a single resolution pipeline used by all three parsers
(SAP, utility, travel) so alias tables and matching logic stay in one place.

Resolution order (first match wins):
  1. Exact match against any alias in the canonical field's list
  2. Case-insensitive match
  3. Whitespace-collapsed + case-insensitive match  (handles "Billing  Start")
  4. snake_case normalised match  (spaces→underscores, lowercased)
"""

import re


def _to_snake(value: str) -> str:
    """Collapse whitespace to underscores and lowercase — 'Billing Start' → 'billing_start'."""
    return re.sub(r'\s+', '_', value.strip()).lower()


def _clean(header: str) -> str:
    """Strip leading/trailing whitespace and common invisible Unicode characters."""
    return header.strip().lstrip('\ufeff\u200b\u00a0')


def resolve_header(header: str, alias_map: dict[str, list[str]]) -> str | None:
    """
    Resolve a raw CSV header to its canonical field name.

    Args:
        header:    Raw column header string from the CSV file.
        alias_map: Mapping of canonical_name → [alias, alias, ...].
                   The canonical name itself does not need to appear in its alias list.

    Returns:
        Canonical field name string, or None if no alias matches.
    """
    h = _clean(header)
    h_lower = h.lower()
    h_snake = _to_snake(h)

    for canonical, aliases in alias_map.items():
        for alias in aliases:
            if h == alias:                          # 1. exact
                return canonical
            if h_lower == alias.lower():            # 2. case-insensitive
                return canonical
            if h_snake == _to_snake(alias):         # 3. snake_case normalised
                return canonical

    return None


def build_header_map(
    fieldnames: list[str],
    alias_map: dict[str, list[str]],
) -> dict[str, str]:
    """
    Build a mapping of original_header → canonical_name for every recognised column.

    Unrecognised headers are silently omitted; callers can inspect the returned
    dict to detect missing required fields.

    Args:
        fieldnames: Raw header list from csv.DictReader.fieldnames.
        alias_map:  Canonical → aliases mapping (parser-specific).

    Returns:
        Dict mapping each matched raw header to its canonical name.
        Original header strings are preserved as keys for raw_data auditability.
    """
    return {
        raw: canonical
        for raw in fieldnames
        if (canonical := resolve_header(raw, alias_map)) is not None
    }


def to_canonical_row(
    row: dict[str, str],
    header_map: dict[str, str],
) -> dict[str, str]:
    """
    Translate a raw csv.DictReader row into a canonical-keyed dict.

    Only columns present in header_map are included; values are stripped.
    The original row dict (raw_data) should be preserved separately by the caller.
    """
    return {
        header_map[k]: (v or '').strip()
        for k, v in row.items()
        if k in header_map
    }
