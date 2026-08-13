from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str

    aws_region: str
    s3_bucket_name: str
    # Leave unset to use boto3's default credential chain (aws configure / IAM role)
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    # ── Bedrock ───────────────────────────────────────────────────────────
    # Separate from the S3 credentials on purpose: Bedrock needs
    # `bedrock:InvokeModel`, which the key that reaches S3 does not have, and
    # Bedrock may not be enabled in the same region. Leave these unset to fall
    # back to the AWS values above.
    bedrock_region: str | None = None
    bedrock_access_key_id: str | None = None
    bedrock_secret_access_key: str | None = None
    # The `us.` prefix is a cross-region inference profile, not a typo: the
    # current models refuse a bare `anthropic.claude-*` id with "Invocation
    # with on-demand throughput isn't supported".
    bedrock_model_id: str = "us.anthropic.claude-opus-5"
    bedrock_timeout_seconds: float = 120.0
    bedrock_max_retries: int = 3

    max_upload_size_mb: int = 25
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    @property
    def resolved_bedrock_region(self) -> str:
        return self.bedrock_region or self.aws_region

    @property
    def resolved_bedrock_access_key_id(self) -> str | None:
        return self.bedrock_access_key_id or self.aws_access_key_id

    @property
    def resolved_bedrock_secret_access_key(self) -> str | None:
        return self.bedrock_secret_access_key or self.aws_secret_access_key


settings = Settings()
