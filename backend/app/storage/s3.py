import os
import ssl
import sys
import tempfile
from functools import lru_cache
from typing import BinaryIO

import boto3
import certifi
from botocore.client import Config
from botocore.response import StreamingBody
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings


@lru_cache(maxsize=1)
def _ca_bundle_path() -> str:
    """CA bundle for boto3. botocore vendors its own static CA bundle instead of the
    OS trust store, so on corporate networks with a TLS-inspection proxy (e.g. Zscaler)
    -- trusted system-wide via IT policy, but absent from botocore's and certifi's public
    root lists -- verification fails. On Windows, merge the OS root store into certifi's
    bundle so both public and corporate-injected roots are trusted.
    """
    if sys.platform != "win32":
        return certifi.where()

    with open(certifi.where(), encoding="utf-8") as f:
        bundle = f.read()

    for store in ("CA", "ROOT"):
        for der, _encoding, _trust in ssl.enum_certificates(store):
            bundle += ssl.DER_cert_to_PEM_cert(der)

    fd, path = tempfile.mkstemp(prefix="docue_ca_bundle_", suffix=".pem")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(bundle)
    return path


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"} if settings.s3_endpoint_url else {},
        ),
        verify=_ca_bundle_path(),
    )


def ensure_bucket() -> None:
    """Create the configured bucket if it does not exist yet.

    Idempotent and safe on every startup: `head_bucket` is cheap, and MinIO
    returns a plain 404 when the bucket is missing, so `create_bucket` on 404
    is reliable here. Only meaningful against MinIO/local dev -- against real
    AWS S3 the bucket is expected to already exist and this becomes a
    harmless extra `head_bucket` call.
    """
    client = get_s3_client()
    bucket = settings.s3_bucket_name
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status != 404:
            raise RuntimeError(f"could not check bucket '{bucket}': {exc}") from exc
        try:
            client.create_bucket(Bucket=bucket)
        except (BotoCoreError, ClientError) as create_exc:
            raise RuntimeError(f"could not create bucket '{bucket}': {create_exc}") from create_exc


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


def download_file(key: str) -> StreamingBody:
    client = get_s3_client()
    try:
        return client.get_object(Bucket=settings.s3_bucket_name, Key=key)["Body"]
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"S3 download failed for key '{key}': {exc}") from exc


def delete_file(key: str) -> None:
    # best-effort compensating cleanup when a DB write fails after S3 upload succeeded;
    # swallow errors so the original DB failure is what surfaces to the caller
    client = get_s3_client()
    try:
        client.delete_object(Bucket=settings.s3_bucket_name, Key=key)
    except (BotoCoreError, ClientError):
        pass
