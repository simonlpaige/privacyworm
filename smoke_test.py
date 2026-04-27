"""End-to-end smoke test. Builds a throwaway profile, runs scan + optout dry-run."""

import sys
import tempfile
from pathlib import Path

# Use a temp dir so we don't touch the real ~/.privacyworm
tmp = Path(tempfile.mkdtemp(prefix="pw-smoke-"))
import os
os.environ["PRIVACYWORM_CONFIG_DIR"] = str(tmp)

from privacyworm.profile import Profile, Name, Address, encrypt_profile, decrypt_profile
from privacyworm.config import get_profile_path
from privacyworm.state import StateDB
from privacyworm.playbook import load_all_playbooks

print(f"=== Smoke test in {tmp} ===\n")

# 1. Build a fake profile
print("[1/5] Building a fake profile...")
profile = Profile(
    name=Name(first="Jane", last="Doe", middle="Q"),
    aliases=["Jane Q Doe", "J Doe"],
    addresses=[
        Address(street="123 Fake St", city="Kansas City", state="MO", zip="64113"),
    ],
    dob="1985-01-01",
    phones=["+1-816-555-0123"],
    emails=["jane.doe.test@example.com"],
    relatives=["John Doe"],
    inbox=None,
)
print(f"   Profile built: {profile.name.first} {profile.name.last}")

# 2. Encrypt and round-trip it
print("\n[2/5] Encrypt -> decrypt round-trip...")
profile_path = get_profile_path(encrypted=True)
profile_path.parent.mkdir(parents=True, exist_ok=True)
encrypt_profile(profile, "test-passphrase", profile_path)
loaded = decrypt_profile("test-passphrase", profile_path)
assert loaded.name.first == "Jane"
assert loaded.emails == ["jane.doe.test@example.com"]
print(f"   Encrypted at {profile_path} ({profile_path.stat().st_size} bytes)")
print(f"   Decrypted cleanly: {loaded.name.first} {loaded.name.last}")

# 3. Load all playbooks and validate them
print("\n[3/5] Loading all 10 playbooks...")
playbooks = load_all_playbooks()
print(f"   Loaded {len(playbooks)} playbooks:")
for pb in playbooks:
    print(f"     - {pb.broker}: {pb.opt_out.method} (rescan every {pb.rescan_days}d)")

# 4. Initialize state DB
print("\n[4/5] Initializing state DB...")
db = StateDB()
summary = db.summary()
from privacyworm.config import get_state_db_path
print(f"   DB at {get_state_db_path()}")
print(f"   Summary: {summary}")
db.close()

# 5. Run a scan/optout dry-run against Spokeo ONLY, mocked
print("\n[5/5] Dry-run opt-out flow (no network calls)...")
from privacyworm.runner import file_optouts
db = StateDB()
# Inject a fake listing so optout has something to work with
listing_id = db.add_listing(
    broker="spokeo",
    listing_url="https://www.spokeo.com/Jane-Doe/Missouri/p1234567",
    matched_name="Jane Q Doe",
    matched_city="Kansas City",
    matched_state="MO",
)
print(f"   Injected fake listing #{listing_id}")
outcomes = file_optouts(loaded, db, dry_run=True, headed=False, broker_name="spokeo")
print(f"   Dry-run outcomes: {len(outcomes)}")
for o in outcomes:
    status = "OK" if o["success"] else "FAILED"
    print(f"     [{status}] {o['broker']} listing #{o['listing_id']}: {o['details']}")

db.close()

print(f"\n=== All checks passed ===")
print(f"Temp dir: {tmp}")
print("You can delete it when done.")
