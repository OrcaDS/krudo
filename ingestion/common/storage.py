"""Read/write abstraction over the lake, so pipeline code never touches paths or buckets directly.

Paths are lake-relative POSIX strings such as ``bronze/files/doe/...``. They map under
``LAKE_ROOT``. The lake is always local; ``lake_release`` copies it to and from a GitHub
release, so a fresh machine or CI run can restore it.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Protocol

import pyarrow as pa
import pyarrow.parquet as pq

from config.settings import Settings

logger = logging.getLogger(__name__)

TMP_PREFIX = ".~tmp-"  # in-progress writes; never a valid lake file name


class Storage(Protocol):
    """Operations the pipeline needs from the lake."""

    def exists(self, path: str) -> bool: ...

    def read_bytes(self, path: str) -> bytes: ...

    def write_bytes(self, path: str, data: bytes) -> None: ...

    def list(self, prefix: str = "") -> list[str]: ...

    def write_parquet(self, path: str, table: pa.Table, schema: pa.Schema) -> None: ...

    def read_parquet(self, path: str) -> pa.Table: ...


def _clean(path: str, *, allow_root: bool = False) -> PurePosixPath:
    """Validate a lake-relative POSIX path.

    Rejects absolute paths, '..', backslashes and drive letters, so a path means the same
    thing on Windows (development) and Linux (CI, Docker).
    """
    if "\\" in path or ":" in path:
        raise ValueError(f"Invalid lake path (use '/' and no drive letters): {path!r}")
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or (not p.parts and not allow_root):
        raise ValueError(f"Invalid lake path: {path!r}")
    if any(part.startswith(TMP_PREFIX) for part in p.parts):
        raise ValueError(f"Lake path uses the reserved temp prefix: {path!r}")
    return p


class LocalStorage:
    """Lake stored in a local directory."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _full(self, path: str, *, allow_root: bool = False) -> Path:
        full = self.root.joinpath(*_clean(path, allow_root=allow_root).parts).resolve()
        if not full.is_relative_to(self.root):  # defense in depth (e.g. symlinks)
            raise ValueError(f"Lake path escapes LAKE_ROOT: {path!r}")
        return full

    def _atomic_write(self, path: str, writer: Callable[[Path], None]) -> None:
        """Write via a unique temp file, then rename: readers never see a partial file.

        The temp file is removed if the write fails, and concurrent writers never share one.
        """
        target = self._full(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{TMP_PREFIX}{uuid.uuid4().hex}-{target.name}")
        try:
            writer(tmp)
            for wait in (0.1, 0.5, 2.0, None):
                try:
                    os.replace(tmp, target)
                    break
                except PermissionError:  # Windows: a virus scan or indexer briefly holds target
                    if wait is None:
                        raise
                    logger.debug("Retrying replace of %s in %.1f s", path, wait)
                    time.sleep(wait)
        finally:
            tmp.unlink(missing_ok=True)

    def exists(self, path: str) -> bool:
        return self._full(path).exists()

    def read_bytes(self, path: str) -> bytes:
        return self._full(path).read_bytes()

    def write_bytes(self, path: str, data: bytes) -> None:
        self._atomic_write(path, lambda tmp: tmp.write_bytes(data))
        logger.debug("Wrote %d bytes to %s", len(data), path)

    def list(self, prefix: str = "") -> list[str]:
        """All file paths under a prefix (or the file itself), lake-relative and sorted.

        An empty prefix lists the whole lake.
        """
        base = self._full(prefix, allow_root=True)
        if base.is_file():
            files = [base]
        elif base.is_dir():
            files = [p for p in base.rglob("*") if p.is_file()]
        else:
            return []
        return sorted(
            p.relative_to(self.root).as_posix() for p in files if not p.name.startswith(TMP_PREFIX)
        )

    def write_parquet(self, path: str, table: pa.Table, schema: pa.Schema) -> None:
        """Write a table with an explicit schema (no inference), snappy-compressed.

        Overwrites any existing file at ``path``, which keeps re-runs idempotent.
        """
        if not table.schema.equals(schema):
            table = table.cast(schema)  # raises if the data does not fit the schema
        self._atomic_write(path, lambda tmp: pq.write_table(table, tmp, compression="snappy"))
        logger.debug("Wrote %d rows to %s", table.num_rows, path)

    def read_parquet(self, path: str) -> pa.Table:
        return pq.read_table(self._full(path))


def get_storage(settings: Settings) -> Storage:
    """Return the lake storage."""
    return LocalStorage(settings.lake_root)
