# Contributing a Broker Playbook

The whole point of PrivacyWorm being open source is that anyone can add support for a new data broker. Each broker is just a YAML file - no Python required.

## What a Playbook Is

A playbook tells PrivacyWorm three things about a broker:

1. **How to search it** - what URL to hit, what CSS selectors find the results
2. **How to opt out** - web form, email, or manual instructions
3. **How to confirm** - does the broker send a confirmation email? What's in it?

That's it. The YAML file is pure data. It can't run code, import modules, or do anything sneaky. PrivacyWorm validates every field before using it.

## Quick Start: Copy and Edit

The fastest way to add a broker:

```bash
cp playbooks/spokeo.yaml playbooks/newbroker.yaml
```

Then edit the file. Here's the skeleton:

```yaml
broker: newbroker           # lowercase, no spaces - used as the filename
display_name: New Broker    # human-readable name
homepage: https://www.newbroker.com
last_updated: "2026-04-22"  # when you last verified this works
maintainer: "@yourgithub"   # so people know who to ping

search:
  url_template: "https://www.newbroker.com/search/{first}-{last}/{state}"
  method: browser           # 'browser' (Playwright) or 'http' (simple GET)
  listing_selectors:        # CSS selectors that match individual result cards
    - "div.result-card"
  match_fields:             # which fields to check when matching results
    - first_name
    - last_name
    - state

opt_out:
  method: web_form          # 'web_form', 'email', or 'manual'
  url: "https://www.newbroker.com/optout"
  form:
    email_field: "input[name='email']"
    url_field: "input[name='listing_url']"
    submit_button: "button[type='submit']"
  requires_confirmation: true
  confirmation_type: email_link   # 'email_link', 'none', or 'manual_ack'
  confirmation_subject_contains: "Opt Out Confirmation"

rescan_days: 90             # how often the broker re-scrapes (default 90)
legal_basis: "Voluntary opt-out"  # what legal framework applies
```

## Field Reference

### `search` section

| Field | Required | Description |
|-------|----------|-------------|
| `url_template` | Yes | URL with `{first}`, `{last}`, `{state}`, `{city}`, `{zip}` placeholders |
| `method` | Yes | `browser` (Playwright, handles JS) or `http` (simple fetch) |
| `listing_selectors` | Yes | CSS selectors for result elements on the page |
| `match_fields` | Yes | Fields to compare: `first_name`, `last_name`, `state`, `city`, `zip`, `full_name`, `age`, `address`, `phone` |

### `opt_out` section

| Field | Required | Description |
|-------|----------|-------------|
| `method` | Yes | `web_form`, `email`, or `manual` |
| `url` | For web_form | URL of the opt-out page |
| `email_address` | For email | Where to send the opt-out request |
| `form.email_field` | No | CSS selector for the email input |
| `form.url_field` | No | CSS selector for the listing URL input |
| `form.name_field` | No | CSS selector for the name input |
| `form.submit_button` | No | CSS selector for the submit button |
| `requires_confirmation` | No | Does the broker send a confirmation email? (default: false) |
| `confirmation_type` | No | `email_link`, `none`, or `manual_ack` |
| `confirmation_subject_contains` | No | Substring to search for in confirmation email subjects |
| `manual_instructions` | For manual | Free-text instructions shown to the user |

## How to Test Your Playbook

```bash
# Make sure it parses correctly
python -c "from privacyworm.playbook import load_playbook; from pathlib import Path; load_playbook(Path('playbooks/newbroker.yaml'))"

# Run the full test suite (validates all playbooks)
pytest tests/test_playbook_validation.py -v

# Try a scan (with a real or test profile)
privacyworm scan --broker newbroker --headed
```

The `--headed` flag opens a visible browser so you can watch what happens and debug selectors.

## Tips for Finding Selectors

1. Open the broker's website in your browser
2. Search for a common name
3. Right-click a result and "Inspect Element"
4. Look for a wrapping element like `<div class="result-card">` or `<article>`
5. Use that as your `listing_selector`

For opt-out forms, do the same thing on the opt-out page: find the input names and button selectors.

## Submitting Your Playbook

1. Fork the repo
2. Add your YAML file to `playbooks/`
3. Run `pytest` to make sure it validates
4. Open a PR with a note about which broker it covers and how you tested it

That's the whole process. No need to write Python, no need to understand the internals. Just YAML and CSS selectors.
