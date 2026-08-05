import os
import uuid
from typing import BinaryIO, Protocol

from app.config import Settings


class MediaStore(Protocol):
    def save(self, data: BinaryIO, filename: str) -> str: ...
    def open(self, path: str) -> BinaryIO: ...


class LocalMediaStore:
    def __init__(self, root: str):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def save(self, data: BinaryIO, filename: str) -> str:
        ext = os.path.splitext(filename)[1] or ".mp4"
        rel = f"{uuid.uuid4().hex}{ext}"
        with open(os.path.join(self.root, rel), "wb") as f:
            while chunk := data.read(1 << 20):
                f.write(chunk)
        return rel

    def open(self, path: str) -> BinaryIO:
        return open(os.path.join(self.root, path), "rb")


class GCSMediaStore:
    def __init__(self, bucket: str):
        from google.cloud import storage

        self.bucket = storage.Client().bucket(bucket)

    def save(self, data: BinaryIO, filename: str) -> str:
        import uuid as _uuid

        ext = os.path.splitext(filename)[1] or ".mp4"
        rel = f"media/{_uuid.uuid4().hex}{ext}"
        self.bucket.blob(rel).upload_from_file(data, content_type="video/mp4")
        return rel

    def open(self, path: str) -> BinaryIO:
        import io

        buf = io.BytesIO()
        self.bucket.blob(path).download_to_file(buf)
        buf.seek(0)
        return buf


def get_store(settings: Settings) -> MediaStore:
    if settings.media_backend == "gcs":
        return GCSMediaStore(settings.gcs_bucket)
    return LocalMediaStore(settings.media_root)
