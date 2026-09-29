from app.config import Settings, to_async_url


def test_railway_url_normalized() -> None:
    assert to_async_url("postgresql://u:p@h:5432/db") == "postgresql+asyncpg://u:p@h:5432/db"
    assert to_async_url("postgres://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"


def test_secrets_not_in_repr(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-super-secret")
    s = Settings()
    assert "sk-super-secret" not in repr(s)
    assert s.anthropic_api_key is not None
    assert s.anthropic_api_key.get_secret_value() == "sk-super-secret"
