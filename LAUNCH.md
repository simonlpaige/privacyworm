# PrivacyWorm Launch Plan

When v1 works end-to-end on at least 3 brokers (Spokeo + 2 more), we launch.

## Principles
- **Be honest.** This is v1, it's rough, we need help. Don't oversell.
- **Feynman voice.** Plain language. No marketing speak. No em dashes.
- **Show the itch.** DeleteMe is $129/yr closed-source. We're free, open, runs local. That's the hook.
- **Ask for playbooks, not stars.** The repo lives or dies based on how many brokers are covered. The ask is: "contribute a playbook for a broker we don't cover yet."

## Channels (in order)

### 1. Hacker News — "Show HN"
Best window: Tue-Thu, 8-10am CT (peaks with US East Coast morning).

**Title** (keep under 80 chars):
`Show HN: PrivacyWorm – open-source agent that files data-broker opt-outs for you`

**Body:**
```
Hi HN,

I got tired of paying DeleteMe $129/year to do something that's basically
"fill out 50 opt-out forms on my behalf." So I built an open-source version
that runs on your own machine.

How it works:
- You fill in a profile once (name, addresses, phones, emails) -- stored
  encrypted on your disk, never uploaded anywhere.
- The agent scans data-broker sites for listings that match you.
- For each match, it files the broker's opt-out request. Some are web
  forms, some are email, some still want a fax (really). It handles the
  boring parts and surfaces captchas to you when they come up.
- It tracks everything in a local SQLite DB and re-scans every 90 days
  because brokers re-list your info.

The design choice that matters: brokers are described in YAML playbooks,
not code. Adding a new broker is a pull request with a ~40-line YAML file.
This is the uBlock Origin model applied to data removal.

v1 ships with [N] brokers working end-to-end. The real goal is community
playbooks for the long tail. If you have a broker that DeleteMe covers and
we don't, please send a PR.

Repo: https://github.com/simonlpaige/privacyworm
Playbook spec: https://github.com/simonlpaige/privacyworm/blob/main/docs/PLAYBOOK_SPEC.md

A few honest caveats:
- Brokers will re-scrape you. This is a maintenance relationship, not a
  one-shot. The tool re-runs on a schedule.
- Some brokers still require ID verification. The agent pauses and asks
  you to upload a redacted ID image when that happens.
- Legal basis varies by state. CCPA and similar laws give you a right to
  opt out; most brokers honor it voluntarily anyway.

Not trying to sell anything. MIT licensed. Would love feedback and PRs.
```

**Replies to expect and pre-draft:**
- "Why not just use X?" -> Name X. Explain honest differences. Don't trash X.
- "Does it handle [weird broker]?" -> "Not yet. PR welcome. Here's the playbook spec."
- "What about the legal side?" -> Link to SECURITY.md / LEGAL.md.
- "How do you handle CAPTCHA?" -> Headed browser mode pauses; user solves; resume.
- "Is this a business?" -> "No. MIT. If someone wants to host a managed version for non-technical folks, go for it -- license permits it."

### 2. Mastodon
Post on mastodon.social first (broadest reach). Cross-post to infosec.exchange (the right crowd specifically).

**Post:**
```
Launched a little open-source project today: PrivacyWorm.

It's an agent that runs on your own machine, scans data broker sites
(Spokeo, Whitepages, the whole crew) for listings matching you, and
files opt-out requests on your behalf. No central server. No account.
Your personal info never leaves your computer.

It's basically DeleteMe but free and open, and the broker handling is
YAML playbooks that anyone can PR. Works on 10 US brokers in v1.

Looking for help covering more brokers. If you've ever wanted your
name off one of those creepy people-search sites, this might be useful,
and if you want to help it cover more of them, even better.

MIT licensed. Python. Runs on Mac, Windows, Linux.

https://github.com/simonlpaige/privacyworm

#privacy #opensource #DataBrokers #selfhosting
```

### 3. Relevant Subreddits (after HN lands)
Only post after HN has had its day. Redditors hate cross-posting that looks like a blitz.

- r/privacy (be in-community, not a drive-by)
- r/selfhosted (focus on the local-first angle)
- r/opensource (focus on the community-playbook angle)
- r/degoogle (privacy angle, different crowd)

Don't post to all four the same day. One per day, and read the subreddit rules first. Some require a certain account age or karma.

### 4. Lobsters
Low volume but high-quality audience. Tag: `privacy, security, show`. Same body as HN roughly but shorter.

### 5. Follow-up Blog Post (if launch lands)
Write a short "how it works" post on Simon's blog / Groundlayer site after we see HN traction. Good for SEO and gives a permanent canonical reference.

## What NOT to do
- Don't post to Twitter/X. Different audience, different work, and we're building open-source plumbing, not a consumer brand.
- Don't email journalists. Too early. Let it be word-of-mouth for v1.
- Don't run ads. This is community work; ads break the trust.
- Don't make a Product Hunt launch. PH audience skews toward closed-source SaaS; it's the wrong crowd.
- Don't promise a managed/hosted version unless we're really going to build one. Overpromising kills trust faster than anything.

## Success Signals (first 72 hours)
- HN: front page for a few hours, 50+ comments, any comments at all from people with domain expertise (privacy researchers, broker insiders, lawyers).
- GitHub: 100+ stars is fine, but the real signal is 3+ PRs for new broker playbooks from strangers.
- Mastodon: 20+ boosts and one reply from someone who actually tries it.
- Email/issue: at least one "I tried it and X broke" that we can turn into a fix within 24 hours.

## If It Flops
That's fine. Not every launch lands. If HN yawns:
- Check the front-page timing (did we post against a huge news day?)
- Check the title (did it sound like marketing?)
- Reread the body. First paragraph is everything. Rewrite and try a second "Show HN: [new angle]" in 6-8 weeks -- HN is cool with that if the project has meaningful new content.

## Prep Checklist (before hitting Submit on HN)

The bar before launch is higher than "the demo works." A privacy
tool that overpromises gets torn apart in the comments.

- [ ] One broker fully confirmed removed end-to-end. The verification block in that playbook reads `scan: live_e2e` and `optout: confirmed_removed`.
- [ ] Three brokers fixture-tested AND dry-run accurate (not just parsed). `privacyworm test-playbooks` is green for each.
- [ ] README support table reflects actual verification status, generated from playbook metadata. No optimistic copy.
- [ ] `privacyworm review` approval flow exists and works on a real scan.
- [ ] `network.log` is redacted by default. `privacyworm export-audit` round-trips.
- [ ] `SECURITY.md` describes Fernet (AES-128-CBC + HMAC-SHA256) and Argon2id, not "AES-256."
- [ ] California users see the DROP nudge. `--skip-drop-reminder` silences it.
- [ ] Known Limitations section visible near the top of README.
- [ ] CI green: ruff, mypy, bandit, pip-audit, pytest with coverage reported.
- [ ] Install instructions tested on Mac and at least one of {Linux, Windows}.
- [ ] CONTRIBUTING.md is readable by someone who's never seen the project.
- [ ] PLAYBOOK_SPEC.md is clear enough that a non-author could write one.
- [ ] Issue templates exist (bug, new-broker-request, playbook-submission).
- [ ] LICENSE file is MIT.
- [ ] At least one broker works end-to-end with a screencast or GIF in README.
- [ ] Simon has half a day clear to reply to comments within 30 min of posting.

That last one matters most. HN rewards authors who show up.
