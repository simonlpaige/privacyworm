"""Rebuild privacyworm/data/brokers.json from the public CPPA registry.

    python scripts/build_registry.py

CI runs this monthly and opens a PR when the list changes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from privacyworm.registry import BUNDLED_PATH, download, save  # noqa: E402

brokers = download()
if len(brokers) < 100:
    sys.exit(f"Only {len(brokers)} brokers parsed - refusing to overwrite.")
save(brokers, BUNDLED_PATH)
print(f"Wrote {len(brokers)} brokers to {BUNDLED_PATH}")
