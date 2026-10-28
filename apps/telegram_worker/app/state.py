"""Private atomic collector identity and reconciliation receipts; SQL owns price data."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile


class CollectorState:
    def __init__(self, path: str, account_id: int):
        self.path = Path(path)
        if not self.path.is_absolute() or self.path.is_symlink():
            raise ValueError("An absolute private state file is required")
        self.lease = None
        if os.name == "posix":
            import fcntl
            self.lease = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BaseException:
                os.close(self.lease)
                self.lease = None
                raise
        try:
            fingerprint = hashlib.sha256(f"telegram-reader:{account_id}".encode()).hexdigest()
            self.data = {"schema_version": 1, "account_fingerprint": fingerprint, "sources": {}}
            if self.path.exists():
                if self.path.stat().st_size > 1_048_576:
                    raise ValueError("Collector state exceeds its size limit")
                loaded = json.loads(self.path.read_text(encoding="utf8"))
                if (not isinstance(loaded, dict) or loaded.get("schema_version") != 1
                        or loaded.get("account_fingerprint") != fingerprint
                        or not isinstance(loaded.get("sources"), dict)):
                    raise ValueError("Collector account or state identity differs")
                self.data = loaded
            self.save()
        except BaseException:
            self.close()
            raise

    def receipt(self, source_id: int, **values) -> None:
        sources = self.data["sources"]
        if len(sources) >= 128 and str(source_id) not in sources:
            raise ValueError("Collector source limit exceeded")
        sources[str(source_id)] = values
        self.save()

    def close(self) -> None:
        if self.lease is not None:
            os.close(self.lease)
            self.lease = None

    def save(self) -> None:
        if not self.path.parent.is_dir():
            raise ValueError("Private collector state directory must exist")
        descriptor, temporary = tempfile.mkstemp(prefix=".collector-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf8") as stream:
                json.dump(self.data, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
