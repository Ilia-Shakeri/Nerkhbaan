"""Safety checks for private relocation preparation, without contacting a host."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import prepare_host_move as move


class HostMoveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def kit(self):
        files = []
        for name in [*("backup/" + n for n in move.SELECTED), "source.tar", "original-backup-manifest.json"]:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"owned test data")
            files.append({"path": name, "bytes": path.stat().st_size, "sha256": move.digest(path)})
        data = {"kind": "nerkhbaan-private-host-move-v1", "live_ready": False,
                "source_commit": "a" * 40, "files": files}
        self.write(data)
        return data

    def write(self, data):
        (self.root / "KIT_MANIFEST.json").write_text(json.dumps(data), encoding="utf8")

    def test_escape_rejected(self):
        for name in ("../secret", "/etc/passwd", "C:/secret", "backup\\..\\secret"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                move.child(self.root, name)

    def test_valid_kit_and_tamper(self):
        self.kit()
        with patch.object(move, "DUMP_SHA256", move.digest(self.root / "backup/production.dump")):
            self.assertFalse(move.verify(self.root)["live_ready"])
            (self.root / "backup/configuration/configuration-3.private.env").write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                move.verify(self.root)

    def test_manifest_cannot_omit_or_duplicate_sensitive_files(self):
        data = self.kit()
        for files in (data["files"][:-1], data["files"] + data["files"][:1]):
            self.write(data | {"files": files})
            with self.assertRaises(ValueError):
                move.verify(self.root)

    def test_unpinned_source_rejected(self):
        data = self.kit()
        self.write(data | {"source_commit": "main"})
        with self.assertRaises(ValueError):
            move.verify(self.root)

    def test_false_live_acceptance_rejected(self):
        data = self.kit()
        self.write(data | {"live_ready": True})
        with self.assertRaises(ValueError):
            move.verify(self.root)

    def test_output_cannot_overwrite_original_backup(self):
        backup = self.root / "original"
        backup.mkdir()
        with self.assertRaises(ValueError):
            move.prepare(backup, backup / "nested")
        with self.assertRaises(ValueError):
            move.prepare(backup, self.root)

    def test_backup_identity_cannot_be_relabelled(self):
        self.kit()
        backup = self.root / "backup"
        rows = [{"path": p.relative_to(backup).as_posix(), "bytes": p.stat().st_size,
                 "sha256": move.digest(p)} for p in backup.rglob("*") if p.is_file()]
        (backup / "manifest.json").write_text(json.dumps({"files": rows}))
        with self.assertRaises(ValueError):
            move.verified_backup(backup)


if __name__ == "__main__":
    unittest.main()
