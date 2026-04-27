"""Extract structured fields from a listing card using a playbook.

The playbook describes each field as either:

  field_name: "css.selector::attr(href)"   # single value
  field_name: "css.selector::text"         # text of the matched node
  field_name:
    selector: "css.selector"
    many: true                              # collect every match

This module turns a chunk of HTML into a dict shaped like::

    {"full_name": "Simon Paige", "city_state": "Kansas City, MO", ...}

It does no scoring; that lives in matching.py. The extract layer is
about turning a soup of <div>s into named fields the rest of the
system can reason about.
"""

from __future__ import annotations

import re
from typing import Any

from privacyworm.playbook import ExtractField

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - only hit when bs4 isn't installed
    BeautifulSoup = None  # type: ignore[assignment]


_SELECTOR_SUFFIX = re.compile(r"::(text|attr\(([^)]+)\))$")


def _parse_selector(spec: str) -> tuple[str, str | None]:
    """Split "div.foo::attr(href)" into (selector, "attr:href")."""
    match = _SELECTOR_SUFFIX.search(spec)
    if not match:
        return spec.strip(), None
    selector = spec[: match.start()].strip()
    if match.group(1) == "text":
        return selector, "text"
    return selector, f"attr:{match.group(2)}"


def _value_from(node, mode: str | None) -> str | None:
    """Pull a string out of a BeautifulSoup node based on the mode."""
    if node is None:
        return None
    if mode is None or mode == "text":
        return (node.get_text(strip=True) or None) if hasattr(node, "get_text") else str(node).strip() or None
    if mode.startswith("attr:"):
        attr = mode.split(":", 1)[1]
        value = node.get(attr) if hasattr(node, "get") else None
        return value if value else None
    return None


def extract_listing(node, spec: dict[str, Any]) -> dict[str, Any]:
    """Apply the extract spec to a single listing-card node."""
    out: dict[str, Any] = {}
    for field, raw in spec.items():
        if isinstance(raw, ExtractField):
            many = raw.many
            selector, mode = _parse_selector(raw.selector)
        elif isinstance(raw, dict):
            many = bool(raw.get("many"))
            selector, mode = _parse_selector(raw.get("selector", ""))
        else:
            many = False
            selector, mode = _parse_selector(str(raw))

        if not selector:
            continue
        try:
            matches = node.select(selector)
        except Exception:
            matches = []

        if many:
            out[field] = [_value_from(m, mode) for m in matches if _value_from(m, mode)]
        else:
            out[field] = _value_from(matches[0], mode) if matches else None
    return out


def extract_listings_from_html(
    html: str,
    listing_selectors: list[str],
    extract_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    """Walk every listing card in ``html`` and pull fields per the spec."""
    if BeautifulSoup is None:
        raise RuntimeError(
            "beautifulsoup4 is required for playbook extract/test. "
            "Install with: pip install beautifulsoup4"
        )

    soup = BeautifulSoup(html, "html.parser")
    nodes = []
    for sel in listing_selectors:
        nodes.extend(soup.select(sel))

    return [extract_listing(n, extract_spec) for n in nodes]
