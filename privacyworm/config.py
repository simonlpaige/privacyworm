"""Load and manage the PrivacyWorm config directory at ~/.privacyworm/."""

import os
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".privacyworm"
PROFILE_FILENAME = "profile.yaml"
ENCRYPTED_PROFILE_FILENAME = "profile.yaml.enc"
STATE_DB_FILENAME = "state.db"
NETWORK_LOG_FILENAME = "network.log"


def get_config_dir() -> Path:
    """Return the config directory, creating it if needed."""
    config_dir = Path(os.environ.get("PRIVACYWORM_CONFIG_DIR", str(DEFAULT_CONFIG_DIR)))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_profile_path(encrypted: bool = True) -> Path:
    """Return path to the profile file."""
    filename = ENCRYPTED_PROFILE_FILENAME if encrypted else PROFILE_FILENAME
    return get_config_dir() / filename


def get_state_db_path() -> Path:
    """Return path to the SQLite state database."""
    return get_config_dir() / STATE_DB_FILENAME


def get_network_log_path() -> Path:
    """Return path to the network request log."""
    return get_config_dir() / NETWORK_LOG_FILENAME
