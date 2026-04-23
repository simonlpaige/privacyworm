"""Load and validate broker playbooks from YAML files."""

from pathlib import Path
from typing import Optional

import tldextract
import yaml
from pydantic import BaseModel, field_validator, model_validator

PLAYBOOKS_DIR = Path(__file__).parent.parent / "playbooks"

VALID_OPT_OUT_METHODS = {"web_form", "email", "manual"}
VALID_CONFIRMATION_TYPES = {"email_link", "none", "manual_ack"}
VALID_SEARCH_METHODS = {"browser", "http"}
VALID_MATCH_FIELDS = {"first_name", "last_name", "state", "city", "zip", "full_name", "age", "address", "phone"}


class SearchConfig(BaseModel):
    url_template: str
    method: str = "browser"
    listing_selectors: list[str] = []
    match_fields: list[str] = []

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        if v not in VALID_SEARCH_METHODS:
            raise ValueError(f"search method must be one of {VALID_SEARCH_METHODS}, got '{v}'")
        return v


class FormConfig(BaseModel):
    email_field: Optional[str] = None
    url_field: Optional[str] = None
    name_field: Optional[str] = None
    submit_button: Optional[str] = None
    extra_fields: dict[str, str] = {}


class OptOutConfig(BaseModel):
    method: str
    url: Optional[str] = None
    email_address: Optional[str] = None
    email_subject: Optional[str] = None
    email_body_template: Optional[str] = None
    form: Optional[FormConfig] = None
    requires_confirmation: bool = False
    confirmation_type: str = "none"
    confirmation_subject_contains: Optional[str] = None
    confirmation_link_text: Optional[str] = None
    manual_instructions: Optional[str] = None

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        if v not in VALID_OPT_OUT_METHODS:
            raise ValueError(f"opt_out method must be one of {VALID_OPT_OUT_METHODS}, got '{v}'")
        return v

    @field_validator("confirmation_type")
    @classmethod
    def validate_confirmation_type(cls, v: str) -> str:
        if v not in VALID_CONFIRMATION_TYPES:
            raise ValueError(f"confirmation_type must be one of {VALID_CONFIRMATION_TYPES}, got '{v}'")
        return v


def _registered_domain(url: str) -> str:
    extracted = tldextract.extract(url)
    return f"{extracted.domain}.{extracted.suffix}" if extracted.suffix else extracted.domain


class Playbook(BaseModel):
    broker: str
    display_name: str
    homepage: str
    last_updated: str
    maintainer: str = "@community"
    search: SearchConfig
    opt_out: OptOutConfig
    rescan_days: int = 90
    legal_basis: Optional[str] = None

    @model_validator(mode="after")
    def validate_url_schemes_and_domains(self) -> "Playbook":
        homepage_domain = _registered_domain(self.homepage)

        url_template = self.search.url_template
        if not url_template.startswith("https://"):
            raise ValueError(
                f"search.url_template must use https://, got: {url_template!r}"
            )
        template_domain = _registered_domain(url_template)
        if template_domain != homepage_domain:
            raise ValueError(
                f"search.url_template domain {template_domain!r} does not match "
                f"homepage domain {homepage_domain!r}"
            )

        if self.opt_out.url is not None:
            if not self.opt_out.url.startswith("https://"):
                raise ValueError(
                    f"opt_out.url must use https://, got: {self.opt_out.url!r}"
                )
            optout_domain = _registered_domain(self.opt_out.url)
            if optout_domain != homepage_domain:
                raise ValueError(
                    f"opt_out.url domain {optout_domain!r} does not match "
                    f"homepage domain {homepage_domain!r}"
                )

        return self


def load_playbook(path: Path) -> Playbook:
    """Load and validate a single playbook from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return Playbook(**data)


def load_all_playbooks(directory: Path | None = None) -> list[Playbook]:
    """Load all playbooks from the playbooks directory."""
    if directory is None:
        directory = PLAYBOOKS_DIR
    playbooks = []
    for yaml_file in sorted(directory.glob("*.yaml")):
        playbooks.append(load_playbook(yaml_file))
    return playbooks


def get_playbook(broker_name: str, directory: Path | None = None) -> Playbook | None:
    """Load a specific playbook by broker name."""
    if directory is None:
        directory = PLAYBOOKS_DIR
    path = directory / f"{broker_name}.yaml"
    if path.exists():
        return load_playbook(path)
    return None
