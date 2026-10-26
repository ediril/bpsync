import pytest

from wpsync.config import ConfigurationStore


@pytest.fixture
def store(tmp_path):
    return ConfigurationStore(tmp_path / "home" / "config.json")
