import os
import ssl
import sys
import tempfile
from functools import lru_cache
from typing import BinaryIO

import boto3
import certifi
from botocore.client import Config
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

    fd, path = tempfile.mkstemp(prefix="templatehub_ca_bundle_", suffix=".pem")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(bundle)
    return path


def get_s3_client():
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        config=Config(signature_version="s3v4"),
        verify=_ca_bundle_path(),
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
