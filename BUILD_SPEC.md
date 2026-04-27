# PrivacyWorm — Build Spec (v1)

## What this is
An open-source agent that scans data-broker sites for your info and files opt-out requests on your behalf. Think DeleteMe ($129/yr, closed, SaaS) but:
- **Runs on your machine.** No central server holds your PII.
- **Community-maintained playbooks.** Each broker is a YAML file in `playbooks/`. Anyone can PR a new one.
- **MIT licensed.**

## Voice
Commit messages and user-facing copy use **Richard Feynman "Curious Explainer" voice.** Simple language, vivid analogies, playful tone. No AI-speak, no marketing adjectives, **no em dashes ever** — use regular dashes or reword. Hard rule.

## v1 Scope (what ships first)
- Python 3.11+ CLI
- Top 10 US data brokers, fully working end-to-end:
  1. Spokeo
  2. Whitepages
  3. BeenVerified
  4. Intelius
  5. PeopleFinder
  6. Radaris
  7. MyLife
  8. TruePeopleSearch
  9. FastPeopleSearch
  10. USPhoneBook
- Each broker = one YAML playbook in `playbooks/<broker>.yaml` describing:
  - `search_url` template
  - `match_selectors` (how to find the user's listing)
  - `opt_out_method`: `web_form` | `email` | `manual`
  - `opt_out_url` / `opt_out_email`
  - `required_fields` (name, address, DOB, phone, email)
  - `confirmation_type`: `email_link` | `none` | `manual_ack`
  - `rescan_days`: 90 (default, brokers re-scrape)

## Architecture

```
privacyworm/
├── README.md                  # user-facing, Feynman voice
├── LICENSE                    # MIT
├── pyproject.toml
├── privacyworm/
│   ├── __init__.py
│   ├── cli.py                 # Click-based CLI
│   ├── config.py              # loads ~/.privacyworm/config.yaml
│   ├── profile.py             # user profile schema (Pydantic)
│   ├── playbook.py            # YAML playbook loader + validator
│   ├── runner.py              # orchestrator: scan -> match -> opt-out -> log
│   ├── brokers/
│   │   ├── base.py            # BaseBroker abstract class
│   │   ├── web_form.py        # Playwright-driven form filler
│   │   └── email.py           # SMTP-based email opt-out
│   ├── inbox/
│   │   ├── base.py
│   │   └── imap.py            # read confirmation emails via IMAP
│   └── state.py               # SQLite: listings found, opt-outs filed, re-scan schedule
├── playbooks/
│   ├── spokeo.yaml
│   ├── whitepages.yaml
│   └── ... (10 total for v1)
├── tests/
│   ├── test_playbook_validation.py
│   ├── test_profile.py
│   └── fixtures/
└── docs/
    ├── CONTRIBUTING.md        # how to add a broker playbook
    ├── PLAYBOOK_SPEC.md       # YAML schema reference
    └── SECURITY.md            # how PII is handled (stored local, encrypted at rest)
```

## CLI Surface

```bash
privacyworm init                        # interactive profile setup, writes ~/.privacyworm/config.yaml (encrypted)
privacyworm scan                        # run scanner across all playbooks
privacyworm scan --broker spokeo        # single broker
privacyworm optout                      # file opt-outs for all matched listings
privacyworm optout --dry-run            # show what WOULD be sent, don't send
privacyworm status                      # listings found, opt-outs pending, confirmations received
privacyworm rescan                      # re-check brokers on schedule (run via cron/task scheduler)
privacyworm inbox check                 # poll IMAP for confirmation emails and process them
```

## Profile (encrypted on disk, AES-256 with user passphrase)

```yaml
# ~/.privacyworm/profile.yaml (encrypted as profile.yaml.enc)
name:
  first: "Simon"
  last: "Paige"
  middle: "L"
aliases:
  - "Simon L Paige"
  - "Simon Paige"
addresses:
  - street: "123 Example St"
    city: "Kansas City"
    state: "MO"
    zip: "64113"
    from_year: 2018
    to_year: null   # current
dob: "1985-06-15"
phones:
  - "+1-816-555-0123"
emails:
  - "simon@example.com"
relatives:          # brokers use these to match; helps avoid false positives
  - "Jane Paige"
inbox:
  type: imap
  host: imap.gmail.com
  port: 993
  user: confirmations@example.com
  pass_env: PRIVACYWORM_INBOX_PASS   # read from env, never stored in file
```

## Playbook Example

```yaml
# playbooks/spokeo.yaml
broker: spokeo
display_name: Spokeo
homepage: https://www.spokeo.com
last_updated: 2026-04-22
maintainer: "@community"

search:
  url_template: "https://www.spokeo.com/{first}-{last}/{state}"
  method: browser   # requires Playwright
  listing_selectors:
    - "article.person-result"
  match_fields:
    - first_name
    - last_name
    - state
    - city

opt_out:
  method: web_form
  url: "https://www.spokeo.com/optout"
  form:
    email_field: "input[name='email']"
    url_field: "input[name='listing_url']"
    submit_button: "button[type='submit']"
  requires_confirmation: true
  confirmation_type: email_link
  confirmation_subject_contains: "Spokeo Opt Out"
  confirmation_link_text: "Confirm"

rescan_days: 90
legal_basis: "CCPA if CA resident; otherwise Spokeo voluntary opt-out"
```

## Hard Requirements

1. **No telemetry.** No phone-home, no analytics, no crash reporting. If we add any, it's opt-in and off by default.
2. **PII never leaves the user's machine** except to the broker the user is opting out from.
3. **All network requests logged** to `~/.privacyworm/network.log` so users can audit.
4. **Playbooks are data, not code.** A playbook cannot execute arbitrary Python. The YAML schema is strict and validated.
5. **Dry-run mode works for everything.** `--dry-run` on opt-out shows the exact payload that would be sent.
6. **Headed mode option.** `--headed` opens a visible browser so users can watch (and intervene if captcha).
7. **Tests for the core flow.** At minimum: playbook loader, profile validation, state machine transitions. Broker-specific tests are fixture-based (mocked HTML).
8. **Windows + macOS + Linux.** Python + Playwright covers this natively.

## Out of Scope for v1
- GUI / web UI
- Browser extension
- Non-US brokers (save for v2)
- Automated captcha solving (surface captcha to user, pause, resume)

## v1.1 Additions (social + mugshots)

### Social media comment / post removal

```bash
privacyworm social scan                                    # count old comments and posts
privacyworm social delete    --platform reddit  --older-than 1y
privacyworm social delete    --platform twitter --before 2024-01-01
privacyworm social overwrite --platform reddit  --older-than 6m
privacyworm social delete-account --platform reddit
```

- Reddit and Twitter/X talk to the official APIs over OAuth 2.0 with
  PKCE. No client secret required - the user registers a public app
  and exports its client ID via `PRIVACYWORM_REDDIT_CLIENT_ID` /
  `PRIVACYWORM_TWITTER_CLIENT_ID`.
- Tokens are stored encrypted at `~/.privacyworm/social_tokens.yaml.enc`
  using the same Fernet + PBKDF2 scheme as `profile.yaml.enc`.
- Other platforms (Facebook, Instagram, TikTok, LinkedIn, Pinterest,
  Tumblr, Mastodon) are flagged manual-only with a step-by-step
  walkthrough.
- `delete-account` prints the playbook for any platform: API method,
  manual URL, ordered instructions, estimated days to completion.
  Playbooks live at `playbooks/social/<platform>.yaml`.

### Mugshot site removal

```bash
privacyworm mugshot scan
privacyworm mugshot optout  --dry-run
privacyworm mugshot letters --site mugshots.com --law ccpa
privacyworm mugshot letters --site mugshots.com --law gdpr
```

- Sites are described by the same broker playbook schema, but they
  live in `playbooks/mugshots/<site>.yaml` so they do not pollute
  the data-broker namespace.
- v1.1 ships ten of them: mugshots.com, bustedmugshots.com,
  arrestfacts.com, justmugshots.com, jailbase.com, arrests.org,
  instantcheckmate.com, publicrecords.directory, arrests.com,
  mugshotsandmore.com.
- `letters` writes a one-page PDF (reportlab) citing GDPR Art. 17 or
  the CCPA right-to-delete (Cal. Civ. Code 1798.105). Plain language,
  no scary legalese.

### New dependencies

- `requests>=2.31` is a core dep for the social-platform HTTP API calls.
- `reportlab>=4.0` is an optional extra (`pip install 'privacyworm[mugshot]'`)
  used only by `privacyworm mugshot letters`. Scan, optout, social, etc
  all work without it.

## What "done" looks like for v1
- `privacyworm init` -> `privacyworm scan` -> `privacyworm optout --dry-run` -> `privacyworm optout` works end-to-end against Spokeo with a real test profile.
- 9 more playbooks shipped (may have `method: manual` stubs with instructions if automation is too brittle — that's fine, document it).
- README has a 60-second quickstart.
- CONTRIBUTING.md explains the playbook YAML schema clearly enough that a community member can add a new broker in under an hour.
- Test suite runs green on CI (GitHub Actions).

## Nice-to-Have (if time permits)
- `privacyworm report` — generate a PDF/markdown summary of everything found + filed (useful as evidence for CCPA follow-ups).
- Docker container for running on a home server / NAS.
- SimpleLogin integration for disposable confirmation emails per-broker.

## First Commit Message Example (Feynman voice)
```
Start of PrivacyWorm.

This is a little agent that looks up your name on data-broker websites
(Spokeo, Whitepages, and the rest of the ugly bunch) and asks them to
take your listing down. It runs on your own computer so your personal
info never has to pass through somebody else's server.

Right now it's a skeleton: the CLI works, it knows how to load a
playbook, and it can pretend to file an opt-out. Real broker playbooks
come next.
```

## Go Build
Start with:
1. `pyproject.toml`, `README.md`, `LICENSE` (MIT)
2. Core package scaffolding (config, profile, playbook loader, state db)
3. Spokeo playbook + end-to-end test against a mocked HTML fixture
4. CLI commands wired up
5. 9 more playbooks (can be skeletal with TODO markers if broker is complex)
6. CI workflow (.github/workflows/test.yml)
7. CONTRIBUTING.md + PLAYBOOK_SPEC.md
8. Push to main, open repo

Keep commits small and Feynman-voiced. Aim for v1 working end-to-end on Spokeo before expanding.
