"""Twitter/X tweet scan and deletion via the v2 API."""

import logging
from typing import Optional

import requests

from privacyworm.brokers.base import log_network_request

logger = logging.getLogger("privacyworm")

API_BASE = "https://api.twitter.com/2"


def _headers(token: dict) -> dict:
    return {"Authorization": f"Bearer {token['access_token']}"}


def get_user_id(token: dict) -> str:
    """Return the logged-in account's Twitter user ID (a numeric string)."""
    url = f"{API_BASE}/users/me"
    log_network_request("GET", url, "twitter me")
    r = requests.get(url, headers=_headers(token), timeout=30)
    r.raise_for_status()
    return r.json()["data"]["id"]


def list_tweets(token: dict, user_id: str) -> list[dict]:
    """List the user's tweets, paginating through all results."""
    items: list[dict] = []
    next_token: Optional[str] = None
    base = f"{API_BASE}/users/{user_id}/tweets"
    while True:
        params: dict = {"max_results": 100, "tweet.fields": "created_at,id,text"}
        if next_token:
            params["pagination_token"] = next_token
        log_network_request("GET", base, "twitter user tweets")
        r = requests.get(base, headers=_headers(token), params=params, timeout=30)
        r.raise_for_status()
        body = r.json()
        items.extend(body.get("data") or [])
        next_token = body.get("meta", {}).get("next_token")
        if not next_token:
            break
    return items


def delete_tweet(token: dict, tweet_id: str) -> bool:
    """Delete a single tweet by ID. Returns True if Twitter confirms deletion."""
    url = f"{API_BASE}/tweets/{tweet_id}"
    log_network_request("DELETE", url, f"twitter delete tweet {tweet_id}")
    r = requests.delete(url, headers=_headers(token), timeout=30)
    if r.status_code != 200:
        return False
    try:
        return bool(r.json().get("data", {}).get("deleted"))
    except Exception:
        return False
