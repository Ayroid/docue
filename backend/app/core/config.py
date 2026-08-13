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
    # The `us.` prefix is a cross-region inference profile, not a typo: a bare
    # `anthropic.claude-sonnet-5` is refused with "Invocation with on-demand
    # throughput isn't supported. Retry with the ID or ARN of an inference
    # profile." Sonnet 5 because it is what this account allows -- which is
    # also what plan §10 named for stages ① and ②.
    bedrock_model_id: str = "us.anthropic.claude-sonnet-5"
    # Cohere rather than Titan: it is the embedding model this account allows.
    # 1024 dimensions to match `templates.embedding VECTOR(1024)` in plan §8 --
    # v4 is Matryoshka-trained, so 1024 is a supported output width and not a
    # truncation.
    bedrock_embedding_model_id: str = "cohere.embed-v4:0"
    embedding_dimensions: int = 1024
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
