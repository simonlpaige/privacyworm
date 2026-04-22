# Playbook YAML Schema Reference

Every broker playbook is a single YAML file in `playbooks/`. This document is the full schema reference.

## Top-Level Fields

```yaml
broker: string          # REQUIRED. Lowercase identifier, must match filename (e.g., "spokeo" -> spokeo.yaml)
display_name: string    # REQUIRED. Human-readable name (e.g., "Spokeo")
homepage: string        # REQUIRED. Broker's homepage URL
last_updated: string    # REQUIRED. ISO date when playbook was last verified (e.g., "2026-04-22")
maintainer: string      # Optional. GitHub handle of the maintainer (default: "@community")
rescan_days: integer    # Optional. Days between rescans (default: 90)
legal_basis: string     # Optional. Legal framework for the opt-out request
```

## `search` Section

```yaml
search:
  url_template: string          # REQUIRED. URL with placeholders: {first}, {last}, {state}, {city}, {zip}
  method: "browser" | "http"    # REQUIRED. "browser" uses Playwright, "http" uses a simple GET request
  listing_selectors:            # REQUIRED. List of CSS selectors for result elements
    - string
  match_fields:                 # REQUIRED. List of fields used to match results to the user profile
    - "first_name" | "last_name" | "state" | "city" | "zip" | "full_name" | "age" | "address" | "phone"
```

### URL Template Placeholders

| Placeholder | Source |
|------------|--------|
| `{first}` | Profile first name |
| `{last}` | Profile last name |
| `{state}` | First address state |
| `{city}` | First address city |
| `{zip}` | First address ZIP |

## `opt_out` Section

```yaml
opt_out:
  method: "web_form" | "email" | "manual"   # REQUIRED

  # For web_form method:
  url: string                                # URL of the opt-out page
  form:
    email_field: string                      # CSS selector for email input
    url_field: string                        # CSS selector for listing URL input
    name_field: string                       # CSS selector for name input
    submit_button: string                    # CSS selector for submit button
    extra_fields:                            # Additional fields to fill
      "css_selector": "value_template"       # Value supports {first}, {last}, {email}, {state}

  # For email method:
  email_address: string                      # Where to send the opt-out request
  email_subject: string                      # Subject line (optional, has a sensible default)
  email_body_template: string                # Body template with {full_name}, {listing_url}, {email}

  # For manual method:
  manual_instructions: string                # Free-text instructions shown to the user

  # Confirmation tracking (all methods):
  requires_confirmation: boolean             # Default: false
  confirmation_type: "email_link" | "none" | "manual_ack"   # Default: "none"
  confirmation_subject_contains: string      # Substring to match in confirmation emails
  confirmation_link_text: string             # Link text to look for in confirmation emails
```

## Validation Rules

These are enforced when the playbook is loaded. A playbook that violates any of these will fail to parse:

1. `broker`, `display_name`, `homepage`, `last_updated` are required
2. `search.method` must be `"browser"` or `"http"`
3. `opt_out.method` must be `"web_form"`, `"email"`, or `"manual"`
4. `confirmation_type` must be `"email_link"`, `"none"`, or `"manual_ack"`
5. If `opt_out.method` is `"email"`, `email_address` should be provided
6. If `opt_out.method` is `"web_form"`, `url` and `form` should be provided

## Security Constraints

Playbooks are **data, not code**. The YAML schema is validated by Pydantic and only whitelisted fields are accepted. A playbook cannot:

- Execute Python code
- Import modules
- Use YAML tags that trigger object construction
- Access the filesystem
- Make network requests on its own

All YAML loading uses `yaml.safe_load()`, which rejects any YAML tags that could instantiate Python objects.

## Example: Minimal Playbook

```yaml
broker: example
display_name: Example Broker
homepage: https://www.example.com
last_updated: "2026-04-22"

search:
  url_template: "https://www.example.com/search?q={first}+{last}"
  method: browser
  listing_selectors:
    - "div.result"
  match_fields:
    - first_name
    - last_name

opt_out:
  method: manual
  manual_instructions: >
    Visit https://www.example.com/contact and request removal manually.
```
