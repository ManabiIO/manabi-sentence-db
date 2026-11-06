import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from manabi_sentence_db import cohort_planner as s


class SelectorTests(unittest.TestCase):
    def fixture(self):
        inv = sqlite3.connect(":memory:")
        inv.execute(
            "CREATE TABLE works(id TEXT PRIMARY KEY,archive TEXT,build TEXT,topic TEXT,priority TEXT,existing INTEGER,kept INTEGER)"
        )
        consumer = sqlite3.connect(":memory:")
        consumer.execute("CREATE TABLE works(id TEXT PRIMARY KEY)")
        self.addCleanup(inv.close)
        self.addCleanup(consumer.close)
        return inv, consumer

    def test_round_robin_coverage_exclusions_oversize_and_output(self):
        inv, current = self.fixture()
        rows = [
            ("a2", "x", "bx", "a", "2", 0, 2),
            ("b1", "y", "by", "b", "1", 0, 20),
            ("a1", "x", "bx", "a", "1", 0, 3),
            ("b2", "y", "by", "b", "2", 0, 2),
            ("old", "x", "bx", "a", "0", 1, 3),
            ("new", "x", "bx", "a", "0", 0, 3),
            ("prior", "x", "bx", "a", "0", 0, 3),
            ("zero", "x", "bx", "a", "0", 0, 0),
        ]
        inv.executemany("INSERT INTO works VALUES (?,?,?,?,?,?,?)", reversed(rows))
        current.execute("INSERT INTO works VALUES ('new')")
        chunks = s.plan(inv, current, 5, ["prior"])
        self.assertEqual([[r["id"] for r in c] for c in chunks], [["a1"], ["b1"], ["a2", "b2"]])
        self.assertEqual(chunks, s.plan(inv, current, 5, ["prior"]))
        ids = [r["id"] for c in chunks for r in c]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {"a1", "a2", "b1", "b2"})
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp).resolve() / "out"
            manifest = s.emit(chunks, out, 5)
            self.assertEqual(manifest["total_works"], 4)
            self.assertTrue(manifest["chunks"][1]["oversized_single_work"])
            for chunk in manifest["chunks"]:
                for entry in chunk["archives"]:
                    data = json.loads((out / chunk["directory"] / entry["selection"]).read_text())
                    self.assertEqual(data["schema_version"], 1)
                    self.assertEqual(data["build_id"], entry["build_id"])
                    self.assertLessEqual(len(data["work_ids"]), s.MAX_SELECTED_WORKS)
            with self.assertRaises(ValueError):
                s.emit(chunks, out, 5)

    def test_empty(self):
        inv, current = self.fixture()
        self.assertEqual(s.plan(inv, current, 1), [])

    def test_invalid_budgets(self):
        inv, current = self.fixture()
        for budget in (0, -1, True, 1.5, "10", None):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                s.plan(inv, current, budget)

    def test_conflicting_archive_build_even_if_excluded(self):
        inv, current = self.fixture()
        inv.executemany(
            "INSERT INTO works VALUES (?,?,?,?,?,?,?)",
            [("a", "x", "b1", "a", "1", 0, 1), ("b", "x", "b2", "a", "2", 1, 0)],
        )
        with self.assertRaisesRegex(ValueError, "conflicting build"):
            s.plan(inv, current, 5)

    def test_selection_limit(self):
        inv, current = self.fixture()
        inv.executemany(
            "INSERT INTO works VALUES (?,?,?,?,?,?,?)",
            [("w%06d" % i, "x", "b", "a", "%06d" % i, 0, 1) for i in range(80001)],
        )
        chunks = s.plan(inv, current, 100000)
        self.assertEqual(list(map(len, chunks)), [80000, 1])

    def test_readonly_connection(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "db.sqlite"
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE works(id TEXT)")
            db.close()
            from contextlib import closing

            with closing(s.readonly(path)) as db:
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute("INSERT INTO works VALUES ('x')")

    def test_reject_invalid_metadata(self):
        for field, value in [
            ("kept", -1),
            ("kept", "broken"),
            ("existing", 2),
            ("build", ""),
            ("id", ""),
        ]:
            with self.subTest(field=field):
                inv, current = self.fixture()
                row = dict(
                    id="a", archive="x", build="b", topic="a", priority="1", existing=0, kept=1
                )
                row[field] = value
                inv.execute("INSERT INTO works VALUES (?,?,?,?,?,?,?)", tuple(row.values()))
                with self.assertRaises(ValueError):
                    s.plan(inv, current, 5)

    def test_prior_validation_and_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "prior.json"
            for ids in ("abc", [1], ["a", "a"], [], [None]):
                path.write_text(json.dumps(dict(schema_version=1, build_id="b", work_ids=ids)))
                with self.subTest(ids=ids), self.assertRaises(ValueError):
                    s.load_prior(path)
            path.write_text(json.dumps(dict(schema_version=1, build_id="", work_ids=["a"])))
            with self.assertRaises(ValueError):
                s.load_prior(path)
            path.write_text(json.dumps(dict(schema_version=1, build_id="b", work_ids=["a"])))
            ids, receipt = s.load_prior(path)
            self.assertEqual(ids, ["a"])
            self.assertEqual(len(receipt["sha256"]), 64)

    def test_changed_input_aborts_before_emission(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            inv, current = self.fixture()
            inventory, consumer = root / "inv.sqlite", root / "consumer.sqlite"
            inv.backup(sqlite3.connect(inventory))
            current.backup(sqlite3.connect(consumer))
            original = s.input_signature
            calls = 0

            def changed(path):
                nonlocal calls
                calls += 1
                value = original(path)
                if calls > 2:
                    value["stat"][2] += 1
                return value

            output = root / "output"
            with patch.object(s, "input_signature", side_effect=changed):
                with self.assertRaisesRegex(ValueError, "input changed"):
                    s.plan_cohorts(inventory, consumer, 5, output)
            self.assertFalse(output.exists())
            result = s.plan_cohorts(inventory, consumer, 5, output)
            self.assertIn("stat", result["input_receipts"]["inventory"])

    def test_symlink_parent_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "real").mkdir()
            (root / "link").symlink_to(root / "real", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "canonical"):
                s.emit([], root / "link" / "output", 5)


def test_cli_emits_plan_and_rejects_invalid_budget(tmp_path, capsys):
    from manabi_sentence_db.cli import main

    root = tmp_path.resolve()
    inventory, consumer = root / "inventory.sqlite", root / "consumer.sqlite"
    with sqlite3.connect(inventory) as db:
        db.execute("CREATE TABLE works(id,archive,build,topic,priority,existing,kept)")
        db.executemany("INSERT INTO works VALUES (?,?,?,?,?,?,?)", [
            ("a", "source.zip", "build", "food", "1", 0, 2),
            ("b", "source.zip", "build", "travel", "2", 0, 2),
        ])
    with sqlite3.connect(consumer) as db:
        db.execute("CREATE TABLE works(id)")
        db.execute("INSERT INTO works VALUES ('a')")
    output = root / "plan"
    args = ["plan-wikipedia-cohorts", "--inventory", str(inventory),
            "--consumer", str(consumer), "--output", str(output), "--occurrence-budget"]
    assert main(args + ["0"]) == 2
    assert not output.exists()
    assert "positive integer" in capsys.readouterr().err
    assert main(args + ["1"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["works"] == 1 and summary["chunks"] == 1
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["chunks"][0]["oversized_single_work"]
    selection = output / manifest["chunks"][0]["directory"] / "archive-0001.selection.json"
    assert json.loads(selection.read_text())["work_ids"] == ["b"]
