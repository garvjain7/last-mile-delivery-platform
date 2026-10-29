"""MinIO object storage boundary for driver delivery evidence."""

from io import BytesIO

from minio import Minio
from minio.error import S3Error

from services.driver_gateway.app.config import config


class MinIOStorageClient:
    """Upload driver evidence without opening an object-storage connection per request."""

    def __init__(self):
        self.client = Minio(
            config.minio_endpoint,
            access_key=config.minio_access_key,
            secret_key=config.minio_secret_key,
            secure=config.minio_secure,
        )
        self.bucket_name = "pod-photos"

    def upload_evidence(
        self,
        object_key: str,
        file_data: bytes,
        content_type: str,
    ) -> str:
        """Store evidence under a stable event key and return its private object key."""
        if not self.client.bucket_exists(self.bucket_name):
            try:
                self.client.make_bucket(self.bucket_name)
            except S3Error as exc:
                if exc.code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                    raise
        self.client.put_object(
            self.bucket_name,
            object_key,
            BytesIO(file_data),
            length=len(file_data),
            content_type=content_type,
        )
        return object_key
