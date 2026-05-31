from __future__ import annotations

from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    market_gateway_api_key: str
    # HTTP listen port (documented for operators; uvicorn reads the port from the process argv / scripts).
    market_gateway_port: int = 8020
    redis_url: str = "redis://localhost:6379/0"
    # Full URL wins when set (e.g. postgresql+asyncpg://user:pass@host:5432/dbname).
    database_url: str | None = None
    # Same knobs as Backtester4 DatabaseManager (used when database_url is empty).
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "market_user"
    # Set in .env (non-empty) to use POSTGRES_* discrete fields when DATABASE_URL is empty.
    # Passwordless / trust: use DATABASE_URL, e.g. postgresql+asyncpg://market_user@localhost:5432/marketdata
    postgres_password: str | None = None
    postgres_dbname: str = "marketdata"

    enable_schwab_live_data: bool = False
    # Phase 3 Schwab Trader API (token from disk; never commit token file).
    schwab_client_id: str | None = None
    schwab_client_secret: str | None = None
    schwab_redirect_uri: str | None = None  # required for OAuth app registration; token file flow uses token on disk
    schwab_token_file: str | None = None
    # Minimum spacing between Schwab HTTP calls (client-side throttle).
    schwab_min_request_interval_seconds: float = 0.12
    enable_real_trading: bool = False
    quote_ttl_seconds: int = 3
    option_quote_ttl_seconds: int = 3
    option_chain_ttl_seconds: int = 120
    history_ttl_seconds: int = 3600
    event_stream_name: str = "stream:events"
    event_bus_xread_block_ms: int = 5000

    def resolved_asyncpg_dsn(self) -> str | None:
        """DSN for asyncpg, or None to use the sample historical store."""
        url = (self.database_url or "").strip()
        if url:
            u = url
            if "+asyncpg" in u:
                u = u.replace("postgresql+asyncpg://", "postgresql://", 1)
            return u
        # Discrete (Backtester4-style): only when a non-empty password is set.
        # Trust / no password: use DATABASE_URL instead.
        pw = (self.postgres_password or "").strip()
        if not pw:
            return None
        u = quote_plus(self.postgres_user)
        auth = f"{u}:{quote_plus(pw)}"
        db = quote_plus(self.postgres_dbname)
        return (
            f"postgresql://{auth}@{self.postgres_host}:{self.postgres_port}/{db}"
        )
