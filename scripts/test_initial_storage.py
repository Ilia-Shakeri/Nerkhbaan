from pathlib import Path
from unittest.mock import patch
import unittest

import initial_storage as storage


class InitialStorageTests(unittest.TestCase):
    def plan(self):
        return {"owner": "a" * 32, "filesystems": [
            {"name": name, "image": f"/opt/nerkhbaan/storage/{name}.ext4",
             "mount": f"/opt/nerkhbaan/storage/{name}", "bytes": size, "uuid": name + "-uuid"}
            for name, size in (("data", 3 * 1024**3), ("backup", 1024**3))]}

    def test_wrong_root_owner_and_duplicate_filesystems_fail_before_commands(self):
        for root, owner, change in (("/opt/other", "a" * 32, False),
                                    ("/opt/nerkhbaan", "b" * 32, False),
                                    ("/opt/nerkhbaan", "a" * 32, True)):
            plan = self.plan()
            if change:
                plan["filesystems"][1] = plan["filesystems"][0]
            with patch.object(storage, "command") as command:
                with self.assertRaises(ValueError):
                    storage.validate(Path(root), plan, owner)
                command.assert_not_called()

    def test_escape_path_fails_before_access(self):
        plan = self.plan()
        plan["filesystems"][0]["image"] = "/dev/vda1"
        with patch.object(storage, "regular") as regular:
            with self.assertRaises(ValueError):
                storage.validate(Path("/opt/nerkhbaan"), plan, "a" * 32)
            regular.assert_not_called()

    def test_uuid_change_blocks_mount(self):
        plan = self.plan()
        with patch.object(storage, "regular"), patch.object(Path, "stat") as info, \
                patch.object(Path, "is_symlink", return_value=False), \
                patch.object(Path, "is_dir", return_value=True), \
                patch.object(storage, "command", return_value="changed") as command:
            info.return_value.st_size = 3 * 1024**3
            with self.assertRaisesRegex(ValueError, "filesystem identity"):
                storage.validate(Path("/opt/nerkhbaan"), plan, "a" * 32)
            self.assertEqual(command.call_args.args[0][0], "blkid")
            self.assertEqual(command.call_count, 1)

    def test_restart_helper_contains_no_format_or_delete_operation(self):
        source = Path(storage.__file__).read_text()
        for token in ("mkfs", ".unlink(", "rmtree", "docker", "pg_restore"):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
