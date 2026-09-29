"""All server state, as keyed blobs (ADR 0004): the dataset cache and used refresh-token markers.

Keys are slash paths: `cache/<user>/<hash>.json` and `jti/<id>`. `LocalStore` keeps them under
a directory (development and tests); `GcsStore` keeps them in the `dota-analyst-mcp` bucket,
fronted by a local copy so repeat reads stay on the instance. Lifecycle rules on the bucket
expire `cache/` after 7 days and `jti/` after 90.
"""

import os
import tempfile
import time
from pathlib import Path
from typing import Protocol


class Store(Protocol):
    def read(self, key: str) -> tuple[bytes, float] | None:
        """The blob and when it was written (epoch seconds), or None."""

    def write(self, key: str, data: bytes) -> None: ...

    def create(self, key: str) -> bool:
        """Create an empty marker atomically: False if it already existed."""


class LocalStore:
    def __init__(self, root: Path, clock=time.time):
        self.root = Path(root)
        self._clock = clock

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"bad store key {key!r}")
        return path

    def read(self, key: str) -> tuple[bytes, float] | None:
        path = self._path(key)
        if not path.exists():
            return None
        return path.read_bytes(), path.stat().st_mtime

    def write(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        # The write time is the cache's clock; keep it on the injected clock for tests.
        stamp = self._clock()
        os.utime(path, (stamp, stamp))

    def create(self, key: str) -> bool:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "x"):
                return True
        except FileExistsError:
            return False


class GcsStore:
    def __init__(self, bucket: str, local_dir: Path | None = None):
        # Imported lazily: tests and local runs don't need it.
        from google.cloud import storage

        self._bucket = storage.Client().bucket(bucket)
        self._local = LocalStore(
            local_dir or Path(tempfile.gettempdir()) / "dota-analyst"
        )

    def read(self, key: str) -> tuple[bytes, float] | None:
        hit = self._local.read(key)
        if hit is not None:
            return hit
        blob = self._bucket.get_blob(key)
        if blob is None:
            return None
        data = blob.download_as_bytes()
        written = blob.updated.timestamp()
        path = self._local._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (written, written))
        return data, written

    def write(self, key: str, data: bytes) -> None:
        self._bucket.blob(key).upload_from_string(data)
        self._local.write(key, data)

    def create(self, key: str) -> bool:
        from google.api_core.exceptions import PreconditionFailed

        try:
            self._bucket.blob(key).upload_from_string(b"", if_generation_match=0)
            return True
        except PreconditionFailed:
            return False
