# Security: How PrivacyWorm Handles Your Personal Information

PrivacyWorm deals with sensitive personal data. Here's exactly how it works so you can decide whether you trust it.

## Where Your Data Lives

All personal information is stored locally in `~/.privacyworm/`:

| File | Contents | Protection |
|------|----------|------------|
| `profile.yaml.enc` | Your name, addresses, phone numbers, DOB | AES-256 encrypted with your passphrase |
| `state.db` | Which brokers have your listings, opt-out status | SQLite, unencrypted (contains broker names and listing URLs, not your full PII) |
| `network.log` | Every HTTP/SMTP request PrivacyWorm makes | Plaintext log for your audit |

## Encryption Details

- **Algorithm:** Fernet (AES-128-CBC with HMAC-SHA256, from the `cryptography` library)
- **Key derivation:** PBKDF2-HMAC-SHA256 with 480,000 iterations and a random 16-byte salt
- **At rest:** The encrypted profile is a JSON blob containing the salt and ciphertext. Without the passphrase, the data is unreadable.

## What Leaves Your Machine

PrivacyWorm sends data to exactly two types of destinations:

1. **Data broker websites** - during scan (HTTP GET) and opt-out (form POST or SMTP email). Only the minimum required fields are sent.
2. **Your IMAP inbox** - if configured, to check for confirmation emails.

That's it. There is no telemetry, no analytics, no crash reporting, no phone-home of any kind. If we ever add any, it will be opt-in and off by default.

## Network Audit Log

Every network request is logged to `~/.privacyworm/network.log` with a timestamp, method, URL, and purpose. You can read this file to see exactly what PrivacyWorm did on your behalf:

```
2026-04-22T10:00:00+00:00 GET https://www.spokeo.com/Simon-Paige/MO scan
2026-04-22T10:00:05+00:00 POST https://www.spokeo.com/optout opt-out form submission
```

## Playbook Security

Playbooks (the YAML files in `playbooks/`) are loaded with `yaml.safe_load()`, which prevents YAML deserialization attacks. The playbook schema is validated by Pydantic - only whitelisted fields are accepted.

A playbook **cannot**:
- Run arbitrary Python code
- Import modules or access the filesystem
- Make network requests on its own
- Use YAML tags that trigger object instantiation

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
