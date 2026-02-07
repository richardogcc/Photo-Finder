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

__all__ = ["CachedHash", "HashCache"]

_SQLITE_MAX_VARS = 900  # stay well under SQLITE_MAX_VARIABLE_NUMBER (999)


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
            """
            CREATE TABLE IF NOT EXISTS directory_index (
                root TEXT NOT NULL,
                path TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                PRIMARY KEY (root, path)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS directory_meta (
                root TEXT PRIMARY KEY,
                dir_mtime REAL NOT NULL,
                file_count INTEGER NOT NULL,
                scanned_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_directory_index_root ON directory_index(root)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_image_hashes_path ON image_hashes(path)"
        )
        self._conn.commit()

    def get_index(self, root: Path) -> Optional[list[Path]]:
        resolved = str(root.resolve())
        # Check directory metadata for staleness (#5)
        meta = self._conn.execute(
            "SELECT dir_mtime, file_count FROM directory_meta WHERE root = ?",
            (resolved,),
        ).fetchone()
        if meta is None:
            return None
        try:
            current_mtime = root.stat().st_mtime
        except OSError:
            return None
        if current_mtime != meta[0]:
            return None

        rows = self._conn.execute(
            "SELECT path FROM directory_index WHERE root = ?",
            (resolved,),
        ).fetchall()
        if not rows:
            return None
        # Sanity check: file count must match
        if len(rows) != meta[1]:
            return None
        return [Path(r[0]) for r in rows]

    def replace_index(self, root: Path, paths: Iterable[Path]) -> None:
        import time as _time

        resolved_root = str(root.resolve())
        self._conn.execute(
            "DELETE FROM directory_index WHERE root = ?", (resolved_root,),
        )
        data: list[tuple[str, str, int, float]] = []
        for p in paths:
            st = p.stat()  # single stat call per file (#2)
            data.append((resolved_root, str(p.resolve()), st.st_size, st.st_mtime))
        if data:
            self._conn.executemany(
                "INSERT INTO directory_index (root, path, size, mtime) "
                "VALUES (?, ?, ?, ?)",
                data,
            )
        # Store / update directory metadata (#5)
        try:
            dir_mtime = root.stat().st_mtime
        except OSError:
            dir_mtime = 0.0
        self._conn.execute(
            "INSERT INTO directory_meta (root, dir_mtime, file_count, scanned_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(root) DO UPDATE SET "
            "dir_mtime=excluded.dir_mtime, file_count=excluded.file_count, "
            "scanned_at=excluded.scanned_at",
            (resolved_root, dir_mtime, len(data), _time.time()),
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

        path_list = [str(p.resolve()) for p in paths]  # normalize (#8)
        cached: dict[Path, CachedHash] = {}
        algo_val = algorithm.value  # explicit .value (#13)

        # Chunk to stay under SQLITE_MAX_VARIABLE_NUMBER (#4)
        for i in range(0, len(path_list), _SQLITE_MAX_VARS):
            chunk = path_list[i : i + _SQLITE_MAX_VARS]
            placeholders = ",".join("?" for _ in chunk)
            query = (
                "SELECT path, mtime, size, algorithm, hash_size, hash, "
                "width, height "
                "FROM image_hashes "
                f"WHERE algorithm = ? AND hash_size = ? "
                f"AND path IN ({placeholders})"
            )
            rows = self._conn.execute(
                query, [algo_val, hash_size, *chunk],
            ).fetchall()
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

    def upsert_many(
        self,
        hashes: Iterable[ImageHashResult],
        hash_size: int | None = None,
    ) -> None:
        data = []
        for h in hashes:
            hs = hash_size if hash_size is not None else int(h.hash_value.hash.shape[0])
            data.append(
                (
                    str(h.path.resolve()),   # normalize (#8)
                    h.file_mtime,            # from result, no extra stat (#3)
                    h.file_size,
                    h.algorithm.value,       # explicit .value (#13)
                    hs,                      # config hash_size (#15)
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
            file_mtime=cached.mtime,
        )
