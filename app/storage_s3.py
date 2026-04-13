"""
S3-compatible file storage.
Falls back to local disk when S3 is not configured.

Set these in .env to enable S3:
  AWS_ACCESS_KEY_ID
  AWS_SECRET_ACCESS_KEY
  AWS_S3_BUCKET
  AWS_S3_REGION  (default: us-east-1)
  AWS_S3_ENDPOINT_URL  (optional — for R2, Backblaze, MinIO, etc.)
"""

import os
import shutil
from pathlib import Path
from app.config import UPLOAD_DIR, OUTPUT_DIR

_s3 = None
_bucket = None


def _client():
    global _s3, _bucket
    if _s3 is not None:
        return _s3, _bucket
    key    = os.environ.get("AWS_ACCESS_KEY_ID", "")
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    bucket = os.environ.get("AWS_S3_BUCKET", "")
    if not (key and secret and bucket):
        return None, None
    import boto3
    kwargs = dict(
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        region_name=os.environ.get("AWS_S3_REGION", "us-east-1"),
    )
    endpoint = os.environ.get("AWS_S3_ENDPOINT_URL", "")
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    _s3     = boto3.client("s3", **kwargs)
    _bucket = bucket
    return _s3, _bucket


def save_upload(local_path: str, key: str) -> str:
    """Store an upload. Returns storage key (S3 key or local path)."""
    client, bucket = _client()
    if client:
        client.upload_file(local_path, bucket, f"uploads/{key}")
        return f"s3://uploads/{key}"
    return local_path


def save_output(local_path: str, key: str) -> str:
    """Store a processed output. Returns storage key."""
    client, bucket = _client()
    if client:
        client.upload_file(local_path, bucket, f"outputs/{key}")
        return f"s3://outputs/{key}"
    return local_path


def get_output(key: str, dest_path: str) -> bool:
    """Download output to dest_path. Returns True on success."""
    if key.startswith("s3://"):
        client, bucket = _client()
        if not client:
            return False
        s3_key = key.replace("s3://", "")
        client.download_file(bucket, s3_key, dest_path)
        return True
    # Local path
    if Path(key).exists():
        if key != dest_path:
            shutil.copy2(key, dest_path)
        return True
    return False


def is_s3_enabled() -> bool:
    _, bucket = _client()
    return bucket is not None
