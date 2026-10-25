import pytest

from bpsync.config import ConfigurationStore


@pytest.fixture
def store(tmp_path):
    return ConfigurationStore(tmp_path / "home" / "config.json")
