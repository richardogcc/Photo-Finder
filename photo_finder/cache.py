"""
SQLite cache for image hashes.

Stores computed hashes keyed by (path, algorithm, hash_size) and
invalidates entries when file size or mtime changes.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import imagehash

from .hasher import HashAlgorithm, ImageHashResult


@dataclass(frozen=True)
class CachedHash:
    path: Path
    mtime: float
    size: int
    algorithm: HashAlgorithm
    hash_size: int
    hash_hex: str
    width: Optional[int]
    height: Optional[int]


class HashCache:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._ensure_schema()

    def close(self) -> None:
        self._conn.close()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS image_hashes (
                path TEXT NOT NULL,
                mtime REAL NOT NULL,
                size INTEGER NOT NULL,
                algorithm TEXT NOT NULL,
                hash_size INTEGER NOT NULL,
                hash TEXT NOT NULL,
                width INTEGER,
                height INTEGER,
                PRIMARY KEY (path, algorithm, hash_size)
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_image_hashes_path ON image_hashes(path)"
        )
        self._conn.commit()

    def get_cached(
        self,
        paths: Iterable[Path],
        algorithm: HashAlgorithm,
        hash_size: int,
    ) -> dict[Path, CachedHash]:
        if not paths:
            return {}

        path_list = list(paths)
        placeholders = ",".join("?" for _ in path_list)
        query = (
            "SELECT path, mtime, size, algorithm, hash_size, hash, width, height "
            "FROM image_hashes "
            f"WHERE algorithm = ? AND hash_size = ? AND path IN ({placeholders})"
        )
        rows = self._conn.execute(query, [algorithm, hash_size, *path_list]).fetchall()
        cached: dict[Path, CachedHash] = {}
        for row in rows:
            cached[Path(row[0])] = CachedHash(
                path=Path(row[0]),
                mtime=row[1],
                size=row[2],
                algorithm=HashAlgorithm(row[3]),
                hash_size=row[4],
                hash_hex=row[5],
                width=row[6],
                height=row[7],
            )
        return cached

    def upsert_many(self, hashes: Iterable[ImageHashResult]) -> None:
        data = []
        for h in hashes:
            hash_size = int(h.hash_value.hash.shape[0])
            data.append(
                (
                    str(h.path),
                    h.path.stat().st_mtime,
                    h.file_size,
                    h.algorithm.value,
                    hash_size,
                    str(h.hash_value),
                    None,
                    None,
                )
            )
        if not data:
            return
        self._conn.executemany(
            """
            INSERT INTO image_hashes
                (path, mtime, size, algorithm, hash_size, hash, width, height)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path, algorithm, hash_size) DO UPDATE SET
                mtime=excluded.mtime,
                size=excluded.size,
                hash=excluded.hash,
                width=excluded.width,
                height=excluded.height
            """,
            data,
        )
        self._conn.commit()

    @staticmethod
    def to_result(cached: CachedHash) -> ImageHashResult:
        return ImageHashResult(
            path=cached.path,
            hash_value=imagehash.hex_to_hash(cached.hash_hex),
            algorithm=cached.algorithm,
            file_size=cached.size,
        )
