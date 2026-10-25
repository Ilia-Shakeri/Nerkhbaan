from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import operator_access as access


class OperatorAccessTests(unittest.TestCase):
    def test_workspace_move_preserves_separate_evidence_roots(self):
        with tempfile.TemporaryDirectory() as folder:
            layout = Path(folder) / "renamed parent"
            for name in ("repo", "delivery", "delivery-desktop"):
                (layout / name).mkdir(parents=True)
            (layout / "repo/package.json").write_text(json.dumps({"name": "nerkhbaan-monorepo"}))
            paths = access.workspace_paths(layout / "repo")
            self.assertEqual(paths["repo"], (layout / "repo").resolve())
            self.assertNotEqual(paths["delivery"], paths["delivery_desktop"])
            (layout / "delivery-desktop").rmdir()
            with self.assertRaises(ValueError):
                access.workspace_paths(layout / "repo")

    def test_wrong_repository_is_rejected_before_access(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "package.json").write_text('{"name":"other-product"}')
            with self.assertRaisesRegex(ValueError, "identity"):
                access.workspace_paths(root)

    def test_existing_source_is_bound_without_connecting(self):
        with patch.object(access.socket, "socket") as factory:
            probe = factory.return_value.__enter__.return_value
            self.assertEqual(access.source_address("10.12.0.5"), "10.12.0.5")
            probe.bind.assert_called_once_with(("10.12.0.5", 0))
            probe.connect.assert_not_called()

    def test_missing_source_does_not_silently_use_another_interface(self):
        with patch.object(access.socket, "socket") as factory:
            factory.return_value.__enter__.return_value.bind.side_effect = OSError("not present")
            with self.assertRaises(OSError):
                access.ssh_arguments()

    def test_invalid_source_is_rejected(self):
        for address in ("0.0.0.0", "127.0.0.1", "::1", "not-an-address"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                access.source_address(address)

    def test_target_host_key_and_noninteractive_identity_stay_pinned(self):
        with patch.object(access, "source_address", return_value="10.12.0.5"):
            args = access.ssh_arguments()
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertIn("BatchMode=yes", args)
        self.assertEqual(args[-1], "deploy@87.248.130.63")
        self.assertEqual(args[args.index("-p") + 1], "9011")

    def test_failed_remote_command_runs_once_and_hides_private_output(self):
        with patch.object(access, "ssh_arguments", return_value=["ssh"]) as arguments, patch.object(access.subprocess, "run") as run:
            run.return_value = MagicMock(returncode=1, stderr="fixture-secret")
            with self.assertRaises(RuntimeError) as raised:
                access.ssh_python("print('inspection')")
            self.assertNotIn("fixture-secret", str(raised.exception))
            self.assertEqual(raised.exception.result.stderr, "fixture-secret")
            run.assert_called_once()
            arguments.assert_called_once()

    def test_modified_legacy_helper_is_rejected_before_import(self):
        with tempfile.TemporaryDirectory() as folder:
            delivery = Path(folder)
            helper = delivery / "release-2.8.13-20261021/release_control.py"
            helper.parent.mkdir()
            helper.write_text("raise RuntimeError('must never execute')")
            with patch.object(access, "workspace_paths", return_value={"delivery_desktop": delivery}):
                with self.assertRaisesRegex(ValueError, "hash changed"):
                    access.release_control()

    def test_deadline_does_not_retry_unknown_remote_completion(self):
        with patch.object(access, "ssh_arguments", return_value=["ssh"]), patch.object(access.subprocess, "run", side_effect=access.subprocess.TimeoutExpired("ssh", 1)) as run:
            with self.assertRaises(access.subprocess.TimeoutExpired):
                access.ssh_python("pass", timeout=1)
            run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
