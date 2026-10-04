# Security: How PrivacyWorm Handles Your Personal Information

PrivacyWorm deals with sensitive personal data. Here's exactly how it works so you can decide whether you trust it.

## Where Your Data Lives

All personal information is stored locally in `~/.privacyworm/` (on Windows, `C:\Users\<you>\.privacyworm\`). The folder is created readable only by you, and every file PrivacyWorm writes there is owner-only (0600 on macOS/Linux).

| File | Contents | Protection |
|------|----------|------------|
| `profile.yaml.enc` | Your name, addresses, phone numbers, DOB, and the optional email app password used for confirmation emails | Fernet (AES-128-CBC + HMAC-SHA256), key derived from your passphrase with Argon2id |
| `social_tokens.yaml.enc` | OAuth tokens for Reddit / Twitter, if configured | Same scheme as the profile |
| `state.db.enc` (or `state.db`) | Broker names, listing URLs, and the score we gave each match | Encrypted with the same passphrase when you set up through guided mode (`privacyworm`). Older installs and `privacyworm init` without `--encrypt-state` keep a plaintext `state.db` |
| `schedule.json` | The date your next check-up is due, and when you were last reminded | Plaintext on purpose: the daily reminder has to read it without your passphrase. It holds no names, URLs or broker list |
| `network.log` | Every HTTP/SMTP/IMAP request PrivacyWorm makes | Plaintext log for your audit. Names and query strings are redacted by default |

## What encryption actually protects

Your profile is encrypted with Fernet (AES-128-CBC for confidentiality plus HMAC-SHA256 for integrity, from the `cryptography` library). The encryption key is derived from your passphrase with Argon2id, the modern memory-hard password hash.

This protects against:
- Someone stealing your `profile.yaml.enc` from a backup, a stolen disk, or a synced cloud folder, without knowing your passphrase.

It does **not** protect against:
- Someone with active access to your running machine, who can read the decrypted profile out of memory while PrivacyWorm is running.
- A weak passphrase. Argon2id is slow on purpose, but a four-character password is still a four-character password. Use a passphrase you would not put in a password manager because it would feel embarrassing how short it is.
- Malware running as your user account. Same threat as any other local-file-based tool.

## Encryption Details

- **Algorithm:** Fernet (AES-128-CBC with HMAC-SHA256, from the `cryptography` library)
- **Key derivation:** Argon2id with `time_cost=3`, `memory_cost=64 MiB`, `parallelism=4`, 32-byte raw output base64-encoded for Fernet
- **Salt:** 16 random bytes per encrypted file, stored next to the ciphertext
- **At rest:** The encrypted file is a JSON envelope with the KDF name, salt, and ciphertext. Without the passphrase, the data is unreadable.

## What Leaves Your Machine

PrivacyWorm sends data to exactly two types of destinations:

1. **Data broker websites** - during scan (HTTP GET) and opt-out (form POST or SMTP email). Only the minimum required fields are sent.
2. **Your IMAP inbox** - if configured, to check for confirmation emails.

That's it. There is no telemetry, no analytics, no crash reporting, no phone-home of any kind. If we ever add any, it will be opt-in and off by default.

## Network Audit Log

`network.log` records every outbound request for auditing. By default, path segments and query strings that look like personal information are replaced with `[REDACTED]`, so the file is safe to share with a friend if you want a second pair of eyes.

```
2026-04-22T10:00:00+00:00 GET https://www.spokeo.com/[REDACTED]/MO scan
2026-04-22T10:00:05+00:00 POST https://www.spokeo.com/optout opt-out form submission
```

Run `privacyworm export-audit --include-sensitive` to dump the full unredacted log when you genuinely need it for debugging.

## State Database

`~/.privacyworm/state.db` is a SQLite file. It contains:

- Broker names (e.g. `spokeo`)
- Listing URLs (the public broker page where your info was found)
- The score and confidence the matching engine gave each listing
- Opt-out status and timestamps

It does **not** contain raw scraped HTML or scraped names; the matching engine uses the scrape and stores only a verdict.

Guided mode (`privacyworm` with no command) encrypts the state database from the first run, using the same passphrase as your profile, so it costs you nothing extra. It is stored as `state.db.enc` and decrypted into a working file only while PrivacyWorm is open. If PrivacyWorm is killed mid-run, that working `state.db` can be left behind; the next run re-encrypts and removes it.

If you set up with `privacyworm init` and want the same protection, run `privacyworm init --encrypt-state`.

You can also wipe local state at any time:

- `privacyworm purge-state` deletes the state database after confirmation.
- `privacyworm delete-profile` deletes the encrypted profile and any social tokens after a clear warning.

## Playbook Security

Playbooks (the YAML files in `playbooks/`) are loaded with `yaml.safe_load()`, which prevents YAML deserialization attacks. The playbook schema is validated by Pydantic - only whitelisted fields are accepted.

A playbook **cannot**:
- Run arbitrary Python code
- Import modules or access the filesystem
- Make network requests on its own
- Use YAML tags that trigger object instantiation

We also reject any playbook URL that is not `https://`, or whose registered domain does not match the homepage. That blocks both SSRF tricks like `file://` and phishing-style "we send your data to evil.com" payloads inside an otherwise innocent-looking playbook.

## Threat Model

PrivacyWorm trusts:
- **Your local filesystem** - if an attacker has access to your machine, they can read the encrypted profile (but still need your passphrase)
- **The data broker websites** - we send them your PII during opt-out (that's the whole point), but only the fields they require
- **Your IMAP provider** - if inbox checking is configured

PrivacyWorm does **not** trust:
- **Playbook files** - treated as untrusted data, validated before use
- **Broker website content** - HTML is parsed with selectors, never executed

## Reporting Security Issues

If you find a security vulnerability, please open a GitHub issue or email the maintainer directly. We take these seriously and will respond quickly.

## Email requests and autopilot

Deletion requests are sent from your own mailbox using an app password you create for PrivacyWorm. The app password is stored inside your encrypted profile. Each letter includes the details a broker needs to find you: name, other names, current and past addresses, phone and email. Your date of birth is deliberately left out. The letter asks the broker to use those details only to locate and delete your records.

When autopilot is on, your profile passphrase is stored in the operating system's credential store (Windows Credential Manager, macOS Keychain, or the Linux Secret Service) so the daily run can unlock your profile without you. Anyone who can log in as you on that computer could read it, the same as your saved browser passwords. `privacyworm autopilot off` deletes it.

Autopilot reads your inbox with IMAP in read-only mode and only downloads full messages that are replies to your requests (matched by email threading, the `[ref PW-XXXXXX]` tag, or the broker's domain). It opens a confirmation link automatically only when the link is on that broker's own registered domain and the email asks you to verify or confirm; anything else goes on your to-do list.

## Reminders and shortcuts

`privacyworm reminders on` registers a once-a-day job with your operating system (Task Scheduler on Windows, launchd on macOS, a systemd user timer or cron on Linux). The job runs `privacyworm remind`, which reads only `schedule.json`. It never unlocks your profile, never opens a browser on its own, and never contacts a broker. When a check-up is due it opens the PrivacyWorm window (or shows a notification on Linux) and you take it from there. `privacyworm reminders off` removes the job.

## Installer

The one-line installers (`install.sh`, `install.ps1`) download [uv](https://github.com/astral-sh/uv) from astral.sh if you don't already have it, then use it to install PrivacyWorm from this GitHub repository into its own isolated environment. Both scripts are short and commented; read them before you run them if you like. PrivacyWorm uses the Chrome or Edge you already have when it can, and only downloads Playwright's Chromium when neither is installed.
