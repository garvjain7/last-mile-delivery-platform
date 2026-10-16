# Forwards POD multi-part photos straight to MinIO
# MinIO S3 object storage client wrapper for proof-of-delivery (POD) image uploads.

from minio import Minio
from services.driver_gateway.app.config import config

class MinIOStorageClient:
    """Storage client managing multi-part POD photo uploads to MinIO bucket."""

    def __init__(self):
        self.client = Minio(
            config.minio_endpoint,
            access_key=config.minio_access_key,
            secret_key=config.minio_secret_key,
            secure=False
        )
        self.bucket_name = "pod-photos"

    async def upload_pod_photo(self, file_name: str, file_data: bytes, content_type: str) -> str:
        """Upload proof-of-delivery photo bytes directly to MinIO bucket."""
        # TODO: Ensure bucket exists and execute put_object upload
        return f"http://{config.minio_endpoint}/{self.bucket_name}/{file_name}"
