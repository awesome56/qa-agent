"""
R2 service — S3-compatible upload to Cloudflare R2 (same account as aperte/examco).
Bucket: qa-reports (created via boto3, same creds as aparte-uploads).
Keys: reports/{project}/{YYYY-MM-DD}/{HH-MM-SS}/{file}
"""
import boto3
from botocore.exceptions import ClientError
from pathlib import Path
from typing import List, Dict, Any, Optional
from app.config import settings

def get_s3():
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
    )

def ensure_bucket():
    s3 = get_s3()
    try:
        s3.head_bucket(Bucket=settings.r2_bucket_name)
    except ClientError:
        try:
            s3.create_bucket(Bucket=settings.r2_bucket_name)
        except Exception as e:
            print(f"[r2] create_bucket failed: {e}")

def upload_file(local_path: Path, r2_key: str, content_type: Optional[str] = None) -> Optional[str]:
    """Uploads local file to R2, returns public URL or r2:// url"""
    s3 = get_s3()
    ensure_bucket()
    extra = {}
    if content_type:
        extra["ContentType"] = content_type
    try:
        s3.upload_file(str(local_path), settings.r2_bucket_name, r2_key, ExtraArgs=extra if extra else None)
        # public URL if bucket has public dev URL or custom domain
        base = settings.r2_public_base_url.rstrip("/")
        # R2 public URL is bucket's public dev URL — for qa-reports we use generic
        # If custom domain not set, fallback to r2://
        if base and "r2.dev" in base:
            return f"{base}/{r2_key}"
        elif base:
            return f"{base}/{r2_key}"
        else:
            return f"r2://{settings.r2_bucket_name}/{r2_key}"
    except Exception as e:
        print(f"[r2] upload failed {local_path} -> {r2_key}: {e}")
        return None

def upload_bytes(data: bytes, r2_key: str, content_type: str = "application/octet-stream") -> Optional[str]:
    s3 = get_s3()
    ensure_bucket()
    try:
        s3.put_object(Bucket=settings.r2_bucket_name, Key=r2_key, Body=data, ContentType=content_type)
        base = settings.r2_public_base_url.rstrip("/")
        if base:
            return f"{base}/{r2_key}"
        return f"r2://{settings.r2_bucket_name}/{r2_key}"
    except Exception as e:
        print(f"[r2] put_bytes failed {r2_key}: {e}")
        return None

def list_reports(prefix: str = "reports/", max_keys: int = 100) -> List[Dict[str, Any]]:
    """Lists R2 objects under prefix, grouped by folder timestamp"""
    s3 = get_s3()
    try:
        resp = s3.list_objects_v2(Bucket=settings.r2_bucket_name, Prefix=prefix, MaxKeys=max_keys)
        objs = resp.get("Contents", [])
        # group by folder (reports/{project}/{date}/{time}/)
        out = []
        for o in objs:
            out.append({"key": o["Key"], "size": o["Size"], "last_modified": o["LastModified"].isoformat(), "url": f"{settings.r2_public_base_url.rstrip('/')}/{o['Key']}" if settings.r2_public_base_url else f"r2://{settings.r2_bucket_name}/{o['Key']}"})
        return out
    except Exception as e:
        print(f"[r2] list failed: {e}")
        return []

def list_folders(prefix: str = "reports/") -> List[str]:
    """List common prefixes (folders) at given prefix"""
    s3 = get_s3()
    try:
        resp = s3.list_objects_v2(Bucket=settings.r2_bucket_name, Prefix=prefix, Delimiter="/", MaxKeys=1000)
        return [p["Prefix"] for p in resp.get("CommonPrefixes", [])]
    except Exception as e:
        print(f"[r2] list_folders failed: {e}")
        return []

def delete_file(key: str) -> bool:
    s3 = get_s3()
    try:
        s3.delete_object(Bucket=settings.r2_bucket_name, Key=key)
        # also try local
        from app.config import REPORTS
        # key is reports/hrms_new/2026-08-21/15-42-01/.../file
        local = REPORTS.parent / key  # REPORTS is /.../storage/reports, so parent is storage
        # Actually REPORTS is storage/reports, so key with reports/... -> storage/reports/...
        # So local path is REPORTS.parent / key -> storage/reports/...
        # For reports/hrms_new/... -> storage/reports/hrms_new/...
        # REPORTS = storage/reports, so REPORTS / key_without_reports
        try:
            lp = REPORTS / key.replace("reports/", "", 1)
            if lp.exists():
                lp.unlink()
        except: pass
        return True
    except Exception as e:
        print(f"[r2] delete_file failed {key}: {e}")
        return False

def delete_prefix(prefix: str) -> int:
    """Delete all objects under prefix (folder), returns count"""
    s3 = get_s3()
    try:
        # list all under prefix
        to_delete = []
        resp = s3.list_objects_v2(Bucket=settings.r2_bucket_name, Prefix=prefix, MaxKeys=1000)
        for o in resp.get("Contents", []):
            to_delete.append({"Key": o["Key"]})
        # handle pagination
        while resp.get("IsTruncated"):
            resp = s3.list_objects_v2(Bucket=settings.r2_bucket_name, Prefix=prefix, ContinuationToken=resp["NextContinuationToken"], MaxKeys=1000)
            for o in resp.get("Contents", []):
                to_delete.append({"Key": o["Key"]})
        if not to_delete:
            return 0
        # batch delete 1000 at a time
        for i in range(0, len(to_delete), 1000):
            batch = to_delete[i:i+1000]
            s3.delete_objects(Bucket=settings.r2_bucket_name, Delete={"Objects": batch})
        # also delete local folder
        try:
            from app.config import REPORTS
            import shutil
            local_folder = REPORTS / prefix.replace("reports/", "", 1)
            if local_folder.exists():
                shutil.rmtree(local_folder, ignore_errors=True)
        except: pass
        return len(to_delete)
    except Exception as e:
        print(f"[r2] delete_prefix failed {prefix}: {e}")
        return 0
