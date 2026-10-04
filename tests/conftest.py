"""Keep every test away from the real ~/.privacyworm folder."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PRIVACYWORM_CONFIG_DIR", str(tmp_path / "pw-config"))
