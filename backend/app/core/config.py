from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str

    aws_region: str
    s3_bucket_name: str
    # Leave unset to use boto3's default credential chain (aws configure / IAM role)
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    max_upload_size_mb: int = 25
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]


settings = Settings()
