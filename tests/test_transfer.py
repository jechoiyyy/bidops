"""Safety boundaries for portable snapshots; actual Docker restore is separate."""

import argparse
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("transfer", Path(__file__).parents[1] / "scripts/transfer.py")
transfer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transfer)


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def sealed(self):
        transfer.write_json(self.root / "manifest/snapshot.json", {"schema_version": transfer.SCHEMA, "state": "captured"})
        (self.root / "data").write_bytes(b"original")
        transfer.write_json(self.root / "manifest/files.json", transfer.file_manifest(self.root))

    def test_changed_missing_and_extra_files_are_rejected(self):
        for mutation in ("changed", "missing", "extra"):
            with self.subTest(mutation=mutation):
                self.sealed()
                if mutation == "changed":
                    (self.root / "data").write_bytes(b"corrupt!")
                elif mutation == "missing":
                    (self.root / "data").unlink()
                else:
                    (self.root / "extra").write_text("not in manifest")
                with self.assertRaises(ValueError):
                    transfer.verify(self.root)

    def test_prepared_folder_cannot_be_restored(self):
        self.sealed()
        transfer.write_json(self.root / "manifest/snapshot.json", {"schema_version": transfer.SCHEMA, "state": "prepared"})
        with self.assertRaises(ValueError):
            transfer.verify(self.root)

    def test_tar_traversal_and_symlink_rejected(self):
        for name, kind in (("../escape", tarfile.REGTYPE), ("/escape", tarfile.REGTYPE),
                           ("link", tarfile.SYMTYPE), ("pipe", tarfile.FIFOTYPE)):
            archive = self.root / "test.tar"
            with tarfile.open(archive, "w") as output:
                item = tarfile.TarInfo(name)
                item.type = kind
                item.linkname = "/outside"
                output.addfile(item, io.BytesIO())
            with self.assertRaises(ValueError):
                transfer.validate_archive(archive)

    def test_lock_is_nonblocking_and_released_after_failure(self):
        lock = self.root / "daily.lock"
        lock.touch()
        with transfer.cron_locks([lock]):
            with self.assertRaises(BlockingIOError):
                with transfer.cron_locks([lock]):
                    pass
        with transfer.cron_locks([lock]):
            pass

    def test_existing_pipeline_link_is_preserved_but_traversal_is_rejected(self):
        archive = self.root / "pipeline.tar"
        def make(*, link="/app/data/runs/original/raw", child=False):
            with tarfile.open(archive, "w") as output:
                item = tarfile.TarInfo("./runs/rerun/raw")
                item.type = tarfile.SYMTYPE
                item.linkname = link
                output.addfile(item)
                if child:
                    output.addfile(tarfile.TarInfo("./runs/rerun/raw/escape"), io.BytesIO())
        make()
        transfer.validate_archive(archive, mountpoint="/app/data")
        make(child=True)
        with self.assertRaises(ValueError):
            transfer.validate_archive(archive, mountpoint="/app/data")
        make(link="/app/data/../../etc/passwd")
        with self.assertRaises(ValueError):
            transfer.validate_archive(archive, mountpoint="/app/data")

    def test_cron_requires_every_shared_lock(self):
        lock = self.root / "daily.lock"
        result = subprocess.CompletedProcess([], 0, f"0 7 * * * flock -w 600 {lock} ./scripts/run-daily-lifecycle.sh\n", "")
        with patch.object(transfer.subprocess, "run", return_value=result):
            transfer.check_cron_locks([lock])
            with self.assertRaises(ValueError):
                transfer.check_cron_locks([self.root / "other.lock"])

    def test_restore_compose_is_offline_read_only_and_dollar_literal(self):
        transfer.write_json(self.root / "config/bind-map.json", {"/host/profile": "inputs/binds/profile"})
        containers = []
        for name in ("web", "postgres", "minio"):
            containers.append({"Image": "sha256:" + "a" * 64,
                "Config": {"Labels": {"com.docker.compose.service": name},
                           "Env": ["PASSWORD=literal${SECRET}", "BIDOPS_SCHEDULER_ENABLED=true"],
                           "Cmd": ["original"], "User": "1000"},
                "Mounts": [{"Type": "volume", "Name": name + "-data", "Destination": "/data"},
                           {"Type": "bind", "Source": "/host/profile", "Destination": "/profile"}]})
        with patch.object(transfer, "docker", side_effect=AssertionError("must not inspect source Docker")):
            config, _ = transfer.compose_config(self.root, containers, "restore-test", 18789,
                                                volume_names=["web-data", "postgres-data", "minio-data"])
        self.assertEqual(set(config["services"]), {"web", "postgres", "minio"})
        web = config["services"]["web"]
        self.assertEqual(web["ports"], ["127.0.0.1:18789:8787"])
        self.assertEqual(web["environment"]["PASSWORD"], "literal$${SECRET}")
        for flag in transfer.OFF_FLAGS:
            self.assertEqual(web["environment"][flag], "false")
        self.assertEqual(web["environment"]["PGOPTIONS"], "-c default_transaction_read_only=on")
        self.assertEqual(web["entrypoint"], ["python", "-m", "uvicorn"])
        self.assertNotIn("depends_on", web)
        self.assertTrue(config["networks"]["private"]["internal"])

    def test_capture_failure_resumes_only_originally_running_services(self):
        containers = []
        for name, running in (("web", True), ("analysis-worker", False), ("postgres", True), ("minio", True)):
            containers.append({"Id": name, "Image": "image", "Config": {"Labels": {"com.docker.compose.service": name}},
                               "State": {"Running": running}})
        transfer.write_json(self.root / "config/containers.json", containers)
        transfer.write_json(self.root / "manifest/snapshot.json", {"schema_version": transfer.SCHEMA, "state": "prepared", "project": "source"})
        lock = self.root / "daily.lock"
        lock.touch()
        with patch.object(transfer, "inventory", return_value=containers), \
             patch.object(transfer, "check_cron_locks"), \
             patch.object(transfer, "assert_no_active_jobs"), \
             patch.object(transfer, "wait_healthy"), \
             patch.object(transfer, "db_summary", side_effect=RuntimeError("dump failed")), \
             patch.object(transfer, "docker") as docker:
            with self.assertRaisesRegex(RuntimeError, "dump failed"):
                transfer.capture(argparse.Namespace(bundle=self.root, confirmed_stop=True, lock_file=[lock]))
        self.assertEqual([c.args for c in docker.call_args_list], [("stop", "--time", "60", "web"), ("start", "web")])
        self.assertFalse((self.root / "manifest/files.json").exists())

    def test_existing_target_project_rejected_before_loading_images(self):
        self.sealed()
        info = transfer.read_json(self.root / "manifest/snapshot.json")
        info["project"] = "source"
        transfer.write_json(self.root / "manifest/snapshot.json", info)
        transfer.write_json(self.root / "manifest/files.json", transfer.file_manifest(self.root))
        with patch.object(transfer, "docker", return_value=b"existing-container") as docker:
            with self.assertRaisesRegex(ValueError, "already has Docker resources"):
                transfer.restore(argparse.Namespace(bundle=self.root, project="restore-test", port=18789,
                                                    target=self.root.parent / "new-target"))
        self.assertEqual(docker.call_count, 1)


if __name__ == "__main__":
    unittest.main()
