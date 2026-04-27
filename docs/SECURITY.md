# Security: How PrivacyWorm Handles Your Personal Information

PrivacyWorm deals with sensitive personal data. Here's exactly how it works so you can decide whether you trust it.

## Where Your Data Lives

All personal information is stored locally in `~/.privacyworm/`:

| File | Contents | Protection |
|------|----------|------------|
| `profile.yaml.enc` | Your name, addresses, phone numbers, DOB | Fernet (AES-128-CBC + HMAC-SHA256), key derived from your passphrase with Argon2id |
| `social_tokens.yaml.enc` | OAuth tokens for Reddit / Twitter, if configured | Same scheme as the profile |
| `state.db` (or `state.db.enc`) | Broker names, listing URLs, and the score we gave each match | SQLite, plaintext by default. Run `privacyworm init --encrypt-state` to encrypt it with the same Fernet key |
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

The default state.db is unencrypted because the user often wants to inspect it from outside Python. If you would prefer it encrypted on disk, run `privacyworm init --encrypt-state` once. It will store as `state.db.enc` and decrypt into a temp file when commands run.

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
