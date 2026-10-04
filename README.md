# PrivacyWorm

PrivacyWorm finds your name, address, phone number and relatives on people-search sites (Spokeo, Whitepages, BeenVerified and friends) and walks you through getting each listing taken down. Then it reminds you to check again, because they come back.

It's the do-it-yourself version of what California's DROP system and paid services like DeleteMe do. It runs on your own computer, so the info needed to find you never goes to anyone else's server, and nothing gets sent to a broker until you say yes.

## Install

No git, no Python, no setup steps. Paste one line and press Enter.

**Mac** - open the Terminal app and paste:

```sh
curl -fsSL https://raw.githubusercontent.com/simonlpaige/privacyworm/main/install.sh | sh
```

**Windows** - open PowerShell (Start menu → type "PowerShell") and paste:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/simonlpaige/privacyworm/main/install.ps1 | iex"
```

Rather click than type? Download [`install.cmd`](https://github.com/simonlpaige/privacyworm/raw/main/install.cmd) and double-click it. (If Windows says "Windows protected your PC", click **More info → Run anyway**.)

**Linux** - same as Mac, in any terminal.

The installer takes a minute or two. It sets up everything PrivacyWorm needs in its own folder (including Python, if you don't have it), uses the Chrome or Edge you already have, and adds **PrivacyWorm** to your Start menu / Applications / app launcher. [What exactly does it do?](docs/SECURITY.md#installer)

**Updating:** run the same install line again. Your saved info is kept.
**Removing:** run `privacyworm uninstall`.

## Use it

Open **PrivacyWorm** from your Start menu, Applications folder or app launcher (or type `privacyworm` in a terminal). It asks you simple questions the whole way:

1. **The first time**, you enter your name, where you live, and an email address, then pick a passphrase to lock it. About 3 minutes.
2. **A check-up** searches each site in the background, then shows you what it found: *"Strong match - matched on your name, city and age. Is this you?"* Press `o` to look at the page, `y` to remove it, `n` if it's someone else.
3. **For each one you said yes to**, PrivacyWorm opens the site's opt-out form with your details already filled in (or an email draft, for sites that take email). You tick the "I'm not a robot" box and click Submit. That's it.
4. **Reminders** (you'll be asked once) make your computer open PrivacyWorm when the next check-up is due, usually every couple of months. The next check-up also shows which listings are now gone.

A first check-up takes 10-20 minutes, most of it the computer searching. Later ones are quicker.

## Good to know

We'd rather you hear the gaps now than be surprised by them.

- **We cover 10 of ~200 major US data brokers.** More come via community PRs. The list below is honest about which playbooks have been live-tested and which are scaffolding.
- **Sites fight automation.** Searches that hit a CAPTCHA are reported as "couldn't check" (never as "clean"), and you can retry them in a visible window. Opt-out forms always leave the final click to you, because that's what gets past their robot checks.
- **Some brokers require ID verification.** PrivacyWorm cannot do that on your behalf - it tells you what the site is asking for and steps out of the way.
- **Brokers re-list you.** Most re-scrape every 60-90 days, which is why PrivacyWorm offers reminders.
- **California residents: use DROP first.** California's Data Removal Operations Platform (drop.oag.ca.gov) reaches the 500+ registered brokers in one request. PrivacyWorm fills the long tail outside that registry.

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

## For power users

Everything the guided mode does is also a plain command, for scripting:

```bash
privacyworm checkup                 # the guided scan -> review -> remove loop
privacyworm scan [--broker spokeo] [--headed]
privacyworm review                  # approve/reject listings one by one
privacyworm optout --approved-only  # file approved opt-outs (--no-assist to auto-submit)
privacyworm status
privacyworm reminders on|off|status
privacyworm doctor                  # check Python, playbooks, browser
privacyworm mugshot scan|optout|letters
privacyworm social scan|delete|overwrite|delete-account
privacyworm inbox check             # find + click confirmation links (shows each URL first)
```

Run `privacyworm --help` or `privacyworm <command> --help` for details.

Settings you can change with environment variables:

| Variable | What it does |
|---|---|
| `PRIVACYWORM_BROWSER=chrome\|msedge\|chromium` | Force a browser (default: first of Chrome, Edge, bundled Chromium) |
| `PRIVACYWORM_BROWSER_PATH` | Use any Chromium-based browser binary (Brave, Vivaldi...) |
| `PRIVACYWORM_SMTP_HOST/PORT/USER/PASS` | Send email opt-outs directly instead of opening a draft in your mail app |
| `PRIVACYWORM_CONFIG_DIR` | Keep data somewhere other than `~/.privacyworm` |
| `PRIVACYWORM_KEEP_RAW_LOG=1` | Also keep an unredacted network log for debugging |

**Developing:** `git clone` the repo, then `uv sync --extra dev --extra mugshot` (or `pip install -e ".[dev,mugshot]"`) and `pytest`.

## How it works

1. **Your profile** is encrypted with Fernet (AES-128-CBC + HMAC-SHA256, key derived from your passphrase with Argon2id) and stored at `~/.privacyworm/profile.yaml.enc`. Your history of listings is encrypted with the same passphrase.
2. **Each broker is a playbook** - a YAML file describing how to search the site and what its opt-out looks like. No code runs from these files; they're pure data, validated by Pydantic, and URL templates can only use plain `{first}`/`{last}`/`{city}`/`{state}`/`{zip}` placeholders.
3. **Each listing gets a score** from comparing it with your profile: name, city, state, ZIP, phone, relatives and age. You see the score and the reasons before deciding.
4. **Nothing is filed without your yes.** Web forms open pre-filled in a visible window; email opt-outs open as a draft in your own mail app (no passwords to configure); sites that need a phone call or ID get step-by-step instructions.
5. **Re-checks track results.** A listing you asked to remove that no longer shows up is marked gone. One that comes back is flagged so you can remove it again.

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
