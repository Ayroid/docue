"""Quick test: upload a local file to S3 using the same upload_file() the API uses."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.storage.s3 import ensure_bucket, get_s3_client, upload_file

MIME_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: uv run python scripts/check_s3.py <path-to-file>")
        return 1

    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"No such file: {path}")
        return 1

    content_type = MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")
    key = f"test-uploads/{path.name}"

    ensure_bucket()
    print(f"Uploading {path.name} ({path.stat().st_size} bytes) to s3://{settings.s3_bucket_name}/{key} ...")
    try:
        with path.open("rb") as f:
            upload_file(f, key, content_type)
    except RuntimeError as exc:
        print(f"FAILED: {exc}")
        return 1

    print("Upload call succeeded. Verifying with head_object ...")
    client = get_s3_client()
    head = client.head_object(Bucket=settings.s3_bucket_name, Key=key)
    print(f"Confirmed in bucket: {head['ContentLength']} bytes, ETag {head['ETag']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
