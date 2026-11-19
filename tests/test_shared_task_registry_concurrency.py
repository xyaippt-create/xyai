import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path

from engine.storage.shared_task_registry import SharedTaskRegistry


def _write_many(root, prefix, count):
    registry = SharedTaskRegistry(Path(root))
    for index in range(count):
        registry[f"{prefix}_{index}"] = {"task_id": f"{prefix}_{index}", "status": "completed"}


class SharedTaskRegistryConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def disk_keys(self, registry):
        return set(json.loads(registry.path.read_text(encoding="utf-8"))["records"])

    def test_two_backends_keep_each_others_results(self):
        first = SharedTaskRegistry(self.root)
        second = SharedTaskRegistry(self.root)  # Started before first wrote anything.
        first["result_a"] = {"result_id": "result_a", "record_kind": "result"}
        second["result_b"] = {"result_id": "result_b", "record_kind": "result"}
        first["result_c"] = {"result_id": "result_c", "record_kind": "result"}
        self.assertEqual(self.disk_keys(first), {"result_a", "result_b", "result_c"})
        self.assertEqual(set(first), {"result_a", "result_b", "result_c"})
        self.assertEqual(second["result_c"]["result_id"], "result_c")
        self.assertEqual(set(SharedTaskRegistry(self.root)), {"result_a", "result_b", "result_c"})

    def test_refresh_keeps_live_in_place_task_edits_and_applies_remote_deletes(self):
        first = SharedTaskRegistry(self.root)
        second = SharedTaskRegistry(self.root)
        first["task_live"] = {"task_id": "task_live", "task_status": "queued"}
        first["task_gone"] = {"task_id": "task_gone", "task_status": "completed"}
        live = first["task_live"]
        live["progress"] = 40  # In-place progress, as the pipeline does.
        del second["task_gone"]
        second["result_remote"] = {"result_id": "result_remote", "record_kind": "result"}
        self.assertEqual(set(first), {"task_live", "result_remote"})
        self.assertIs(first["task_live"], live)
        self.assertEqual(first["task_live"]["progress"], 40)
        first["task_live"] = live
        self.assertEqual(SharedTaskRegistry(self.root)["task_live"]["progress"], 40)

    def test_parallel_processes_lose_no_writes(self):
        SharedTaskRegistry(self.root)["seed"] = {"task_id": "seed"}
        context = multiprocessing.get_context("spawn")
        workers = [context.Process(target=_write_many, args=(str(self.root), prefix, 25)) for prefix in ("a", "b")]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(120)
            self.assertEqual(worker.exitcode, 0)
        keys = set(SharedTaskRegistry(self.root))
        self.assertEqual(len(keys), 51)
        self.assertTrue({f"a_{i}" for i in range(25)} | {f"b_{i}" for i in range(25)} <= keys)


if __name__ == "__main__":
    unittest.main()
