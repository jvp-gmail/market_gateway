from market_gateway.app.config import Settings


def test_resolved_dsn_prefers_database_url() -> None:
    s = Settings(
        market_gateway_api_key="k",
        database_url="postgresql+asyncpg://u:p@db:5432/mydb",
        postgres_password="ignored",
    )
    assert s.resolved_asyncpg_dsn() == "postgresql://u:p@db:5432/mydb"


def test_resolved_dsn_from_discrete_password() -> None:
    s = Settings(
        market_gateway_api_key="k",
        database_url="",
        postgres_host="h",
        postgres_port=5433,
        postgres_user="u",
        postgres_password="p@ss",
        postgres_dbname="d",
    )
    dsn = s.resolved_asyncpg_dsn()
    assert dsn is not None
    assert "postgresql://" in dsn
    assert "h:5433" in dsn
    assert "d" in dsn


def test_resolved_dsn_empty_password_skips_discrete() -> None:
    s = Settings(
        market_gateway_api_key="k",
        database_url=None,
        postgres_password="",
    )
    assert s.resolved_asyncpg_dsn() is None
