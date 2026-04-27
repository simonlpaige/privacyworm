"""Base class for broker interactions."""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from privacyworm.config import get_network_log_path, scrub_pii
from privacyworm.playbook import Playbook
from privacyworm.profile import Profile

logger = logging.getLogger("privacyworm")


def log_network_request(method: str, url: str, details: str = "") -> None:
    """Append a line to the network log so users can audit every request.

    Query strings are stripped before writing; the auditable info is the
    domain and path, not the search parameters that carry the user's name.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    safe_url = scrub_pii(url)
    line = f"{timestamp} {method} {safe_url} {details}\n"
    log_path = get_network_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(line)


class BaseBroker(ABC):
    def __init__(self, playbook: Playbook, profile: Profile, headed: bool = False):
        self.playbook = playbook
        self.profile = profile
        self.headed = headed

    @abstractmethod
    def scan(self) -> list[dict]:
        """Search the broker for listings matching the profile.

        Returns a list of dicts, each with at least:
            - listing_url: str or None
            - matched_name: str
            - matched_city: str or None
            - matched_state: str or None
            - raw_snippet: str or None
        """
        ...

    @abstractmethod
    def file_optout(self, listing: dict, dry_run: bool = False) -> dict:
        """File an opt-out request for a specific listing.

        Returns a dict with:
            - success: bool
            - method: str
            - details: str
        """
        ...

    def _build_search_url(self) -> str:
        """Fill in the search URL template with profile fields."""
        template = self.playbook.search.url_template
        return template.format(
            first=self.profile.name.first,
            last=self.profile.name.last,
            state=self.profile.addresses[0].state if self.profile.addresses else "",
            city=self.profile.addresses[0].city if self.profile.addresses else "",
            zip=self.profile.addresses[0].zip if self.profile.addresses else "",
        )
