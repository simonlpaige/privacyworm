"""Schema and loader for social-platform account-deletion playbooks.

Different from the data-broker ``Playbook``: there is no scan / opt-out
form to fill. Each YAML file describes how to delete an account on one
platform, plus how long the platform takes to honour it.
"""

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

SOCIAL_PLAYBOOKS_DIR = Path(__file__).parent.parent.parent / "playbooks" / "social"


class SocialPlaybook(BaseModel):
    platform: str
    display_name: str
    homepage: str
    api_method: Optional[str] = None
    manual_url: Optional[str] = None
    instructions: list[str] = []
    estimated_days_to_complete: int = 30
    notes: Optional[str] = None


def load_social_playbook(
    platform: str, directory: Path | None = None
) -> Optional[SocialPlaybook]:
    if directory is None:
        directory = SOCIAL_PLAYBOOKS_DIR
    path = directory / f"{platform}.yaml"
    if not path.exists():
        return None
    with open(path) as f:
        data = yaml.safe_load(f)
    return SocialPlaybook(**data)


def load_all_social_playbooks(directory: Path | None = None) -> list[SocialPlaybook]:
    if directory is None:
        directory = SOCIAL_PLAYBOOKS_DIR
    if not directory.exists():
        return []
    out: list[SocialPlaybook] = []
    for f in sorted(directory.glob("*.yaml")):
        with open(f) as fh:
            out.append(SocialPlaybook(**yaml.safe_load(fh)))
    return out
