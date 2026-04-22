"""Base class for inbox watchers that look for confirmation emails."""

from abc import ABC, abstractmethod


class BaseInbox(ABC):
    @abstractmethod
    def check_confirmations(self, subject_contains: str) -> list[dict]:
        """Search for confirmation emails matching the given subject substring.

        Returns a list of dicts with:
            - subject: str
            - from_addr: str
            - body: str
            - links: list[str] (URLs found in the body)
            - uid: str (message identifier for marking as processed)
        """
        ...

    @abstractmethod
    def click_confirmation_link(self, url: str) -> bool:
        """Visit a confirmation link and return True if it succeeded."""
        ...
