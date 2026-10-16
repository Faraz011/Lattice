import pytest

from lattice.config import ConfigError, load_settings

REQUIRED = {
    "LATTICE_NEO4J_URI": "bolt://localhost:7687",
    "LATTICE_NEO4J_USER": "neo4j",
    "LATTICE_NEO4J_PASSWORD": "secret-pw",
    "LATTICE_REDIS_URL": "redis://localhost:6379/0",
    "LATTICE_APPROVER_TOKEN": "approver-token",
}


@pytest.fixture
def clean_env(monkeypatch):
    for name in list(REQUIRED) + ["LATTICE_LLM_REQUESTS_PER_MINUTE", "LATTICE_RISK_THRESHOLD"]:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_loads_all_required_values_from_environment(clean_env):
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)

    settings = load_settings(env_file=None)

    assert settings.neo4j_uri == "bolt://localhost:7687"
    assert settings.neo4j_password.get_secret_value() == "secret-pw"
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.approver_token.get_secret_value() == "approver-token"


def test_missing_required_variable_is_named_in_the_error(clean_env):
    for name, value in REQUIRED.items():
        if name != "LATTICE_NEO4J_PASSWORD":
            clean_env.setenv(name, value)

    with pytest.raises(ConfigError) as excinfo:
        load_settings(env_file=None)

    message = str(excinfo.value)
    assert "LATTICE_NEO4J_PASSWORD" in message
    assert "LATTICE_REDIS_URL" not in message


def test_every_missing_variable_is_listed(clean_env):
    with pytest.raises(ConfigError) as excinfo:
        load_settings(env_file=None)

    for name in REQUIRED:
        assert name in str(excinfo.value)


def test_invalid_numeric_value_is_rejected_with_its_variable_name(clean_env):
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)
    clean_env.setenv("LATTICE_RISK_THRESHOLD", "1.5")

    with pytest.raises(ConfigError) as excinfo:
        load_settings(env_file=None)

    assert "LATTICE_RISK_THRESHOLD" in str(excinfo.value)


def test_secrets_are_not_shown_in_repr(clean_env):
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)

    settings = load_settings(env_file=None)

    assert "secret-pw" not in repr(settings)
    assert "approver-token" not in repr(settings)
