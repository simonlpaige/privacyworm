"""Reddit comment / post scan and removal via the official OAuth API."""

import logging
from typing import Optional

import requests

from privacyworm.brokers.base import log_network_request

logger = logging.getLogger("privacyworm")

USER_AGENT = "privacyworm/1.0 (open-source privacy agent)"
API_BASE = "https://oauth.reddit.com"


def _headers(token: dict) -> dict:
    return {
        "Authorization": f"Bearer {token['access_token']}",
        "User-Agent": USER_AGENT,
    }


def get_username(token: dict) -> str:
    """Return the logged-in user's Reddit username."""
    url = f"{API_BASE}/api/v1/me"
    log_network_request("GET", url, "reddit me")
    r = requests.get(url, headers=_headers(token), timeout=30)
    r.raise_for_status()
    return r.json()["name"]


def list_user_content(token: dict, kind: str, username: str) -> list[dict]:
    """List a user's content. ``kind`` is ``comments`` or ``submitted``."""
    if kind not in {"comments", "submitted"}:
        raise ValueError(f"kind must be 'comments' or 'submitted', got {kind!r}")

    items: list[dict] = []
    after: Optional[str] = None
    while True:
        url = f"{API_BASE}/user/{username}/{kind}"
        params: dict = {"limit": 100}
        if after:
            params["after"] = after
        log_network_request("GET", url, f"reddit {kind} listing")
        r = requests.get(url, headers=_headers(token), params=params, timeout=30)
        r.raise_for_status()
        body = r.json().get("data", {})
        children = body.get("children", []) or []
        if not children:
            break
        for c in children:
            items.append(c["data"])
        after = body.get("after")
        if not after:
            break
    return items


def delete_thing(token: dict, fullname: str) -> bool:
    """Delete a post or comment by its Reddit ``thing`` fullname (e.g. t1_abc)."""
    url = f"{API_BASE}/api/del"
    log_network_request("POST", url, f"reddit delete {fullname}")
    r = requests.post(url, headers=_headers(token), data={"id": fullname}, timeout=30)
    return r.status_code == 200


def edit_thing(token: dict, fullname: str, text: str) -> bool:
    """Overwrite a comment's text. Reddit only allows editing comments and self-text posts."""
    url = f"{API_BASE}/api/editusertext"
    log_network_request("POST", url, f"reddit edit {fullname}")
    r = requests.post(
        url,
        headers=_headers(token),
        data={"thing_id": fullname, "text": text, "api_type": "json"},
        timeout=30,
    )
    return r.status_code == 200
