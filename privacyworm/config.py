"""Load and manage the PrivacyWorm config directory at ~/.privacyworm/."""

import os
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

DEFAULT_CONFIG_DIR = Path.home() / ".privacyworm"
PROFILE_FILENAME = "profile.yaml"
ENCRYPTED_PROFILE_FILENAME = "profile.yaml.enc"
STATE_DB_FILENAME = "state.db"
ENCRYPTED_STATE_DB_FILENAME = "state.db.enc"
NETWORK_LOG_FILENAME = "network.log"
RAW_NETWORK_LOG_FILENAME = "network.raw.log"

# A path segment is treated as PII when it has both a hyphen or
# underscore AND at least one uppercase letter. That catches name slugs
# (Simon-Paige, Simon-L-Paige) and city slugs (Kansas-City-MO). Bare
# words ("optout"), state codes ("MO"), and numeric IDs ("12345") all
# survive, which keeps the audit log readable.
_NAMEY_PATH_SEGMENT = re.compile(r"^(?=.*[-_])(?=.*[A-Z]).+$")


def get_config_dir() -> Path:
    """Return the config directory, creating it if needed."""
    config_dir = Path(os.environ.get("PRIVACYWORM_CONFIG_DIR", str(DEFAULT_CONFIG_DIR)))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_profile_path(encrypted: bool = True) -> Path:
    """Return path to the profile file."""
    filename = ENCRYPTED_PROFILE_FILENAME if encrypted else PROFILE_FILENAME
    return get_config_dir() / filename


def get_state_db_path(encrypted: bool = False) -> Path:
    """Return path to the SQLite state database."""
    filename = ENCRYPTED_STATE_DB_FILENAME if encrypted else STATE_DB_FILENAME
    return get_config_dir() / filename


def get_network_log_path() -> Path:
    """Return the path to the redacted network log (always written)."""
    return get_config_dir() / NETWORK_LOG_FILENAME


def get_raw_network_log_path() -> Path:
    """Return the path to the raw, unredacted network log.

    The raw log only exists when the user opts in via
    ``PRIVACYWORM_KEEP_RAW_LOG=1``. ``privacyworm export-audit
    --include-sensitive`` reads from here when present.
    """
    return get_config_dir() / RAW_NETWORK_LOG_FILENAME


def keep_raw_log_enabled() -> bool:
    """Read the env flag that opts in to keeping a raw, unredacted log."""
    return os.environ.get("PRIVACYWORM_KEEP_RAW_LOG", "").strip() in ("1", "true", "yes")


def _redact_path(path: str) -> str:
    """Replace name-like path segments with ``[REDACTED]``.

    A segment is considered name-like when it contains a capital letter
    and a hyphen or underscore - the shape brokers use for slugs like
    ``Simon-Paige`` or ``Simon-L-Paige``. Plain words, numeric IDs, and
    two-letter state codes are kept so the URL stays auditable.
    """
    if not path:
        return path
    segments = path.split("/")
    redacted = []
    for seg in segments:
        if seg and _NAMEY_PATH_SEGMENT.match(seg):
            redacted.append("[REDACTED]")
        else:
            redacted.append(seg)
    return "/".join(redacted)


def scrub_pii(url: str) -> str:
    """Return a version of ``url`` safe for the network audit log.

    Query strings and fragments are dropped (they often hold the user's
    name, city, or phone). Path segments that look like name slugs are
    replaced with ``[REDACTED]``. Scheme, host, and the rest of the path
    survive so the user can still see which broker was contacted and at
    which endpoint.
    """
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.scheme and not parts.netloc:
        return url
    return urlunsplit((parts.scheme, parts.netloc, _redact_path(parts.path), "", ""))
