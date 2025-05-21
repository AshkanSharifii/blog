# src/app/core/config.py  (final, defensive version)
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # ── Database & JWT ────────────────────────────────
    database_url: str = Field("sqlite:///./postino.db", env="DATABASE_URL")
    secret_key: str = Field(..., env="SECRET_KEY")
    algorithm: str = Field(..., env="ALGORITHM")
    access_token_expire_minutes: int = Field(
        ..., env="ACCESS_TOKEN_EXPIRE_MINUTES"
    )

    # ── Default admin ────────────────────────────────
    default_user_email: str = Field(..., env="DEFAULT_USER_EMAIL")
    default_user_password: str = Field(..., env="DEFAULT_USER_PASSWORD")

    # ── MinIO (new names) ────────────────────────────
    minio_endpoint: str      = Field(..., env="MINIO_ENDPOINT")
    minio_root_user: str     = Field(..., env="MINIO_ROOT_USER")
    minio_root_password: str = Field(..., env="MINIO_ROOT_PASSWORD")
    minio_bucket: str        = Field(..., env="MINIO_BUCKET")

    # ── Legacy names made optional  (won’t break old code) ───────────
    minio_access_key: str | None = Field(None, env="MINIO_ACCESS_KEY")
    minio_secret_key: str | None = Field(None, env="MINIO_SECRET_KEY")

    # map them back to the new names when someone still uses them
    @property
    def minio_access_key_resolved(self) -> str:
        return self.minio_root_user

    @property
    def minio_secret_key_resolved(self) -> str:
        return self.minio_root_password

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()
