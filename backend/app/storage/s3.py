from typing import BinaryIO

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings


def get_s3_client():
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        config=Config(signature_version="s3v4"),
    )


def upload_file(fileobj: BinaryIO, key: str, content_type: str) -> None:
    client = get_s3_client()
    try:
        client.upload_fileobj(
            fileobj,
            settings.s3_bucket_name,
            key,
            ExtraArgs={"ContentType": content_type},
        )
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"S3 upload failed for key '{key}': {exc}") from exc


def delete_file(key: str) -> None:
    # best-effort compensating cleanup when a DB write fails after S3 upload succeeded;
    # swallow errors so the original DB failure is what surfaces to the caller
    client = get_s3_client()
    try:
        client.delete_object(Bucket=settings.s3_bucket_name, Key=key)
    except (BotoCoreError, ClientError):
        pass
