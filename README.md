# PrivacyWorm

Your personal info is sitting on data-broker websites right now. Spokeo, Whitepages, BeenVerified - they scraped it, packaged it, and they're selling it to anyone with a credit card.

PrivacyWorm is a little agent that crawls those sites, finds your listings, and files opt-out requests to get them taken down. The whole thing runs on your own computer, so your personal details never pass through somebody else's server.

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

The three-step `scan -> review -> optout --approved-only` flow is the
recommended path. Nothing gets filed until you have eyeballed each
listing and said yes.

## How It Works

1. **You tell it who you are.** `privacyworm init` walks you through entering your name, addresses, phone numbers, etc. This gets encrypted and stored locally at `~/.privacyworm/profile.yaml.enc`.

2. **It searches the brokers.** Each broker has a "playbook" - a YAML file that describes how to search that site and what opt-out looks like. No code runs from these files; they're pure data.

3. **It files opt-outs.** For brokers with web forms, it fills them in with Playwright. For email-based opt-outs, it sends the request. Some brokers are stubborn and require manual steps - the tool tells you exactly what to do.

4. **It watches for confirmations.** Many brokers send a confirmation email with a link you need to click. `privacyworm inbox check` monitors your inbox and handles those.

5. **It rescans.** Brokers re-scrape your info every few months. Set up `privacyworm rescan` on a cron job and it'll catch new listings as they appear.

## Supported Brokers (v1)

---
**What 'Supported' means here:** Scan and opt-out have been tested in headed mode against a live session and manually verified within the last 30 days. Most entries are currently WIP - the playbooks and scaffolding exist, but the selectors and opt-out flows need live verification before we can call them reliable.
---

| Broker | Scan | Match | Opt-out | Status |
|--------|------|-------|---------|--------|
| Spokeo | prototype | low confidence | dry-run only | WIP - needs live verification |
| Whitepages | prototype | low confidence | dry-run only | WIP - needs live verification |
| BeenVerified | prototype | low confidence | dry-run only | WIP - needs live verification |
| Intelius | prototype | low confidence | dry-run only | WIP - needs live verification |
| PeopleFinder | prototype | low confidence | dry-run only | WIP - needs live verification |
| Radaris | prototype | low confidence | email template | WIP - needs live verification |
| MyLife | prototype | low confidence | manual/email | WIP - needs live verification |
| TruePeopleSearch | prototype | low confidence | dry-run only | WIP - needs live verification |
| FastPeopleSearch | prototype | low confidence | dry-run only | WIP - needs live verification |
| USPhoneBook | prototype | low confidence | dry-run only | WIP - needs live verification |

## What about California's DROP system?

California's Data Removal Operations Platform (DROP) goes live January 1 2026 and starts processing requests from August 1 2026. California residents can submit one request through DROP to reach the 500+ brokers registered with the state at once.

PrivacyWorm fills a different gap. It covers non-California users, handles brokers that aren't registered with DROP, runs recurring re-checks (brokers re-list you every 90 days), captures evidence of what was found and when, and handles the stubborn brokers that quietly ignore form submissions.

## Privacy Guarantees

- **No telemetry.** Zero phone-home, zero analytics, zero crash reporting.
- **PII stays local.** Your personal info never leaves your machine except when sent directly to a broker during opt-out.
- **Full audit trail.** Every network request is logged to `~/.privacyworm/network.log`.
- **Playbooks are data, not code.** The YAML files can't execute arbitrary Python. They describe selectors and URLs, nothing more.

## Adding a New Broker

Anyone can add a broker by writing a YAML playbook. See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for the full guide - it should take under an hour.

## License

MIT. Do whatever you want with it.
