"""Render the README "Supported Brokers" table from playbook verification metadata.

Run: python scripts/render_support_table.py

Pipes a Markdown table to stdout; paste it under the
"## Supported Brokers" heading in README.md. The table is generated
from the verification block of each playbook so the README cannot
overstate what is actually verified.
"""

import sys
from pathlib import Path

# Make sure the package is importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from privacyworm.playbook import load_all_playbooks  # noqa: E402


def render() -> str:
    rows = []
    rows.append("| Broker | Scan | Opt-out | Verified | Status |")
    rows.append("|--------|------|---------|----------|--------|")
    for pb in sorted(load_all_playbooks(), key=lambda p: p.broker):
        v = pb.verification
        scan = v.scan if v else "fixture_only"
        optout = v.optout if v else "dry_run_only"
        verified_at = v.verified_at if v and v.verified_at else "-"
        if scan == "live_e2e" and optout == "confirmed_removed":
            status = "Verified end-to-end"
        elif scan in {"live_manual", "live_e2e"} and optout in {"submitted", "confirmed_removed"}:
            status = "Live-tested"
        else:
            status = "WIP - needs live verification"
        rows.append(
            f"| {pb.display_name} | {scan} | {optout} | {verified_at} | {status} |"
        )
    return "\n".join(rows) + "\n"


if __name__ == "__main__":
    sys.stdout.write(render())
