# PrivacyWorm

PrivacyWorm is a local-first workbench for finding and removing data broker listings. It scans, shows you the evidence, drafts opt-out requests, tracks status, and keeps the broker playbooks current. It keeps you in the loop - nothing gets filed without your approval.

It runs on your own computer, so the personal info needed to find your listings never has to pass through somebody else's server.

## Known Limitations

Read this before you install. We would rather you understand the gaps now than be surprised by them.

- **We cover 10 of ~200 major US data brokers.** More come via community PRs. The list below is honest about which playbooks have been live-tested and which are scaffolding.
- **Some brokers throw CAPTCHAs.** When that happens, the tool pauses with a visible browser window and asks you to solve it.
- **Some brokers require ID verification.** PrivacyWorm cannot do that on your behalf - it tells you what the site is asking for and steps out of the way.
- **Brokers re-list you.** Most re-scrape every 60-90 days, which is why there is a `rescan` command meant to run on a schedule.
- **California residents: use DROP first.** California's Data Removal Operations Platform (drop.oag.ca.gov) reaches the 500+ registered brokers in one request. PrivacyWorm fills the long tail outside that registry.

## 60-Second Quickstart

```bash
# Install
pip install .

# Install browser for web automation
playwright install chromium

# Set up your profile (interactive, encrypted on disk)
privacyworm init

# See what the brokers have on you
privacyworm scan --headed

# Look at each listing, see the evidence, approve or reject one by one
privacyworm review

# File the opt-outs you approved
privacyworm optout --approved-only

# Check on the status of everything
privacyworm status
```

The three-step `scan -> review -> optout --approved-only` flow is the recommended path. Nothing gets filed until you have eyeballed each listing and said yes.

## How It Works

1. **You tell it who you are.** `privacyworm init` walks you through entering your name, addresses, phone numbers, etc. This gets encrypted with Fernet (AES-128-CBC + HMAC-SHA256, key derived with Argon2id) and stored locally at `~/.privacyworm/profile.yaml.enc`.

2. **It searches the brokers.** Each broker has a "playbook" - a YAML file that describes how to search that site, what fields to extract from a listing card, and what opt-out looks like. No code runs from these files; they're pure data, validated by Pydantic.

3. **It scores each match.** The matching engine compares scraped listings to your profile across full name, city, state, ZIP, phone, relatives, and an age-from-DOB sanity check. Each listing gets a high / medium / low confidence label.

4. **You review every match.** `privacyworm review` shows the score, the matched fields, and the exact opt-out payload that would be sent. You answer y / N / skip / quit. Only listings you approve move on.

5. **It files opt-outs.** For brokers with web forms, it fills them in with Playwright. For email-based opt-outs, it sends the request with the right legal basis for your state. Some brokers are stubborn and require manual steps - the tool tells you exactly what to do.

6. **It watches for confirmations.** Many brokers send a confirmation email with a link you need to click. `privacyworm inbox check` reads your inbox, validates each link's domain and path against the playbook's allowlist, and shows you the URL before clicking.

7. **It rescans.** Brokers re-scrape your info every few months. Set up `privacyworm rescan` on a cron job and it'll catch new listings as they appear.

## Supported Brokers

**What "Supported" means here:** a playbook is only marked Verified when scan and opt-out have been tested end-to-end against a live broker session within the last 30 days, with a confirmed removal on file. Anything else is WIP. The table below is generated from each playbook's `verification` block by `scripts/render_support_table.py`.

| Broker | Scan | Opt-out | Verified | Status |
|--------|------|---------|----------|--------|
| BeenVerified | fixture_only | dry_run_only | 2026-04-27 | WIP - needs live verification |
| FastPeopleSearch | fixture_only | dry_run_only | 2026-04-27 | WIP - needs live verification |
| Intelius | fixture_only | dry_run_only | 2026-04-27 | WIP - needs live verification |
| MyLife | fixture_only | dry_run_only | 2026-04-27 | WIP - needs live verification |
| PeopleFinder | fixture_only | dry_run_only | 2026-04-27 | WIP - needs live verification |
| Radaris | fixture_only | dry_run_only | 2026-04-27 | WIP - needs live verification |
| Spokeo | fixture_only | dry_run_only | 2026-04-27 | WIP - needs live verification |
| TruePeopleSearch | fixture_only | dry_run_only | 2026-04-27 | WIP - needs live verification |
| USPhoneBook | fixture_only | dry_run_only | 2026-04-27 | WIP - needs live verification |
| Whitepages | fixture_only | dry_run_only | 2026-04-27 | WIP - needs live verification |

Plus mugshot site playbooks for ten of the major sites (mugshots.com, bustedmugshots.com, arrestfacts.com, ...) under `playbooks/mugshots/`. Those are also fixture-only at the moment; the `privacyworm mugshot letters` flow generates a CCPA or GDPR PDF you can send manually.

## What about California's DROP system?

California's Data Removal Operations Platform (DROP) went live January 1, 2026. Brokers must process requests by August 1, 2026. California residents can submit one request through DROP to reach the 500+ brokers registered with the state at once.

PrivacyWorm covers the other side. It handles brokers that aren't registered with DROP, runs recurring re-checks (brokers re-list you every 90 days), captures per-listing evidence of what was found and when, and handles the stubborn brokers that quietly ignore form submissions.

Run `privacyworm registries` for the list of state-run registries we know about (California DROP, Texas, Oregon, Vermont).

## Privacy Guarantees

- **No telemetry.** Zero phone-home, zero analytics, zero crash reporting.
- **PII stays local.** Your personal info never leaves your machine except when sent directly to a broker during opt-out.
- **Redacted audit trail.** Every network request is logged to `~/.privacyworm/network.log` with names and query strings replaced by `[REDACTED]`. The file is safe to share when you need help debugging. Run `privacyworm export-audit --include-sensitive` for the raw log when you opted into keeping one.
- **Optional state encryption.** Run `privacyworm init --encrypt-state` and the local listing database is also encrypted at rest.
- **Playbooks are data, not code.** The YAML files can't execute arbitrary Python. They describe selectors and URLs, nothing more.

See [SECURITY.md](docs/SECURITY.md) for the threat model and exactly what encryption protects against.

## Adding a New Broker

Anyone can add a broker by writing a YAML playbook. See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for the full guide and [PLAYBOOK_SPEC.md](docs/PLAYBOOK_SPEC.md) for the schema reference. It should take under an hour. Run `privacyworm test-playbooks` to round-trip your selectors against an HTML fixture before sending the PR.

## License

MIT. Do whatever you want with it.
