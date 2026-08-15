from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str

    aws_region: str
    s3_bucket_name: str
    # Leave unset to use boto3's default credential chain (aws configure / IAM role)
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    # Points boto3 at local MinIO instead of real AWS S3. Leave unset in a
    # real AWS deployment -- `endpoint_url=None` is a no-op for boto3.
    s3_endpoint_url: str | None = None

    # ── LLM proxy ─────────────────────────────────────────────────────────
    # An OpenAI-API-compatible local proxy, not Bedrock. Kept separate from S3
    # credentials on purpose, same as Bedrock was: different service, different
    # key, no reason to couple their configuration.
    llm_base_url: str = "http://localhost:3001/v1"
    llm_api_key: str
    # "auto" lets the proxy pick a default chat backend.
    llm_chat_model: str = "auto"
    # Pinned rather than "auto": the proxy's own default embedding family is
    # gemini-embedding-001 at 3072 dimensions, which would not fit the existing
    # `templates.embedding VECTOR(1024)` column. nv-embedqa-e5-v5 is 1024-dim
    # and free (nvidia backend) -- bge-m3/qwen3-embedding-0.6b are also
    # 1024-dim but their no-key providers were failing ("no usable keys") on
    # this proxy instance at setup time; nv-embedqa-e5-v5 was the one that
    # actually worked when this was verified.
    llm_embedding_model: str = "nv-embedqa-e5-v5"
    embedding_dimensions: int = 1024
    llm_timeout_seconds: float = 120.0

    max_upload_size_mb: int = 25
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # ── auth ──────────────────────────────────────────────────────────────
    # Signs the access tokens. The default is a development value and is
    # refused when `app_env` is anything but `local` -- a shared deployment
    # running on a secret that is in the repository would let anyone mint an
    # admin token.
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    # 12h: long enough to cover a working day without a re-login, short enough
    # that a promotion or a disable takes effect the same day. There is no
    # refresh token -- adding one means a revocation story, and the hub has no
    # place to keep it yet.
    access_token_ttl_minutes: int = 720
    app_env: str = "local"

    # ── email ─────────────────────────────────────────────────────────────
    # Unset `smtp_host` and every message is logged instead of sent, which is
    # the default so a fresh checkout can run the whole OTP flow with no
    # credentials. Set it and the same messages go out over SMTP.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_from: str = "Docue <no-reply@yamaha-motor-india.com>"
    smtp_timeout_seconds: float = 15.0

    # Returns the OTP in the API response so local work does not need a
    # mailbox. Forced off whenever email is really configured or `app_env` is
    # not `local` -- see the validator below.
    otp_debug: bool = True

    # ── admin seed ────────────────────────────────────────────────────────
    # Read by `scripts/seed_admin.py`. Never read at request time: promotion
    # after the first admin exists happens through the admin API, so a stale
    # value here cannot silently re-grant a revoked role.
    seed_admin_email: str | None = None
    seed_admin_username: str = "admin"
    seed_admin_password: str | None = None
    seed_admin_full_name: str = "Admin"

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host)

    @property
    def is_local(self) -> bool:
        return self.app_env.lower() in {"local", "dev", "development"}

    @property
    def expose_otp_in_response(self) -> bool:
        """Whether the OTP is echoed back to the caller.

        Three conditions, all required, because each one alone has failed
        somewhere: the flag is on, this is a local environment, and no real
        mail server is configured. A deployment that sets `APP_ENV=production`
        gets the safe behaviour even if `OTP_DEBUG` was left true in a copied
        `.env`.
        """
        return self.otp_debug and self.is_local and not self.email_configured

    @model_validator(mode="after")
    def _refuse_dev_secret_outside_local(self) -> "Settings":
        """A shared deployment must not sign tokens with the repo's secret.

        Checked here rather than at first use: a bad `JWT_SECRET` should stop
        the process at import, not surface as a forged token weeks later.
        """
        if self.jwt_secret == DEV_JWT_SECRET and not self.is_local:
            raise ValueError(
                "JWT_SECRET is still the development default while APP_ENV="
                f"{self.app_env!r}. Set JWT_SECRET to a random value "
                "(`python -c \"import secrets; print(secrets.token_urlsafe(48))\"`)."
            )
        return self


settings = Settings()
