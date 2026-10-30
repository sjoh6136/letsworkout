import copy
import ast
import json
import time
import unittest
from pathlib import Path
from progression_choices import (TAB, HEADER, atomic_save, attach_choices,
                                 load_choices, validate_choices)
from test_progression import NS
from workout_log_edits import edited_row


class FakeSheet:
    def __init__(self, store, title, ident):
        self.store, self.title, self.id = store, title, ident
        self.rows = [HEADER[:] if title == TAB else ["header"]]

    def get(self, address):
        self.store.reads += 1
        return copy.deepcopy(self.rows[1:])


class FakeStore:
    LOGS_TAB, SUBMISSIONS_TAB, REPLACEMENTS_TAB = "Workout_Logs", "Workout_Submissions", "Workout_Replacements"
    def __init__(self):
        self.sheets = {}
        self.spreadsheet = self
        self.reads = self.writes = 0
        self.fail = self.lose_response = False

    def worksheet(self, title, **kwargs):
        if title not in self.sheets:
            self.sheets[title] = FakeSheet(self, title, len(self.sheets))
        return self.sheets[title]

    def ensure_header(self, *args):
        pass

    def values_batch_get(self, ranges):
        self.reads += 1
        return {"valueRanges": [
            {"values": [[r[0]] for r in self.sheets[self.LOGS_TAB].rows]},
            {"values": copy.deepcopy(self.sheets[TAB].rows[1:])}]}

    def batch_update(self, body):
        self.writes += 1
        if self.fail:
            raise OSError("write rejected")
        for request in body["requests"]:
            append = request["appendCells"]
            sheet = next(s for s in self.sheets.values() if s.id == append["sheetId"])
            sheet.rows.extend([[c["userEnteredValue"]["stringValue"] for c in row["values"]]
                               for row in append["rows"]])
        if self.lose_response:
            raise OSError("response lost after commit")


class ChoicesTests(unittest.TestCase):
    def setUp(self):
        self.name = "덤벨 컬"
        self.ex = dict(name=self.name, sets=3, repsRange="8-12", rpeTarget=8)
        self.choice = dict(mode="on", originalWeight=15, originalReps=8, weight=8, reps=11)
        self.logs = [dict(username="alice", date="2026-10-29", split=2, week=1, day="Day 2",
                          exercise=self.name, setNo=i, weight=8, reps=11, rpe=8, completed=True,
                          targetWeight=15, targetReps=8, status="SUCCESS") for i in range(1, 4)]
        self.submission = dict(id="session-1", date="2026-10-29", split=2, week=1, day="Day 2", createdAt="now")

    def choices(self):
        return validate_choices({self.name: self.choice}, self.logs, {self.name: self.ex})

    def target(self, choices=None):
        choices = choices or self.choices()
        for log in self.logs:
            log["progressionChoice"] = choices[self.name]
        result = NS["next_progression_sets"](self.ex, self.logs, {})
        return result[0]["weight"], result[0]["reps"]

    def test_on_success_and_fail_keep_selected_baseline(self):
        self.assertEqual(self.target(), (8, 12))
        for changes in (dict(reps=6), dict(rpe=9), dict(completed=False), dict(weight=7)):
            old = self.logs[-1].copy()
            self.logs[-1].update(changes)
            self.assertEqual(self.target(), (8, 11))
            self.logs[-1] = old
        self.logs = self.logs[:2]
        self.assertEqual(self.target(), (8, 11))

    def test_off_and_unchanged_are_distinct(self):
        self.choice["mode"] = "off"
        self.assertEqual(self.target(), (15, 8))
        self.choice["mode"] = "unchanged"
        self.assertEqual(self.target(), (15, 8))
        for log in self.logs:
            log.update(weight=15, reps=8)
        self.assertEqual(self.target(), (15, 9))

    def test_heavier_lower_reps_and_assistance(self):
        self.choice.update(originalWeight=30, originalReps=10, weight=40, reps=8)
        for log in self.logs:
            log.update(weight=40, reps=8)
        self.assertEqual(self.target(), (40, 9))
        self.name = self.ex["name"] = "머신 풀업"
        for log in self.logs:
            log["exercise"] = self.name
        self.assertEqual(self.target(), (40, 9))  # Explicit ON also permits easier assistance.
        self.logs[-1]["weight"] = 45
        self.assertEqual(self.target(), (40, 8))

    def test_reload_links_exact_rows_after_edit_and_repeated_sessions(self):
        store = FakeStore()
        choices = self.choices()
        self.assertTrue(atomic_save(store, self.logs, choices, self.submission, "alice"))
        self.assertEqual((store.reads, store.writes), (1, 1))
        self.assertEqual(len(store.sheets[store.LOGS_TAB].rows[1]), 13)
        self.assertEqual(store.sheets[store.LOGS_TAB].rows[1][11:13], ["15", "8"])
        next_logs = copy.deepcopy(self.logs)
        next_choices = {self.name: {**choices[self.name], "weight": 6}}
        atomic_save(store, next_logs, next_choices, {**self.submission, "id": "session-2"}, "alice")
        records = load_choices(store, "alice")
        restored = copy.deepcopy(self.logs + next_logs)
        for log in restored:
            log.pop("progressionChoice", None)
            log["reps"] = 6  # A history edit must not remove the chosen target.
        attach_choices(restored, records, "alice")
        self.assertEqual([r["progressionChoice"]["weight"] for r in restored], [8]*3 + [6]*3)
        self.assertEqual([r["submissionId"] for r in restored], ["session-1"]*3 + ["session-2"]*3)
        self.assertEqual(load_choices(store, "bob"), [])
        row = store.sheets[store.LOGS_TAB].rows[1]
        edited = edited_row(row, dict(weight=8, reps=11, rpe=8, completed=True), choices[self.name])
        self.assertEqual(edited[10], "SUCCESS")
        self.assertEqual(edited[11:13], ["15", "8"])

    def test_atomic_failure_response_loss_and_duplicate_retry(self):
        store = FakeStore()
        store.fail = True
        with self.assertRaises(OSError):
            atomic_save(store, self.logs, self.choices(), self.submission, "alice")
        self.assertEqual(len(store.sheets[store.LOGS_TAB].rows), 1)
        self.assertEqual(len(store.sheets[TAB].rows), 1)
        store.fail, store.lose_response = False, True
        self.assertTrue(atomic_save(store, self.logs, self.choices(), self.submission, "alice"))
        self.assertFalse(atomic_save(store, self.logs, self.choices(), self.submission, "alice"))
        self.assertEqual(len(store.sheets[store.LOGS_TAB].rows), 4)
        self.choice["weight"] = 9
        with self.assertRaises(ValueError):
            atomic_save(store, self.logs, self.choices(), self.submission, "alice")

    def test_reject_invalid_and_missing_choices(self):
        for value in (None, {}, {self.name: {}}, {self.name: {**self.choice, "weight": float("nan")}}):
            with self.assertRaises((ValueError, TypeError)):
                validate_choices(value, self.logs, {self.name: self.ex})

    def test_bulk_save_call_count_does_not_grow_per_exercise(self):
        store = FakeStore()
        many = [{**log, "exercise": f"exercise-{i}"} for i in range(12) for log in self.logs]
        choice = self.choices()[self.name]
        choices = {log["exercise"]: choice for log in many}
        started = time.perf_counter()
        atomic_save(store, many, choices, self.submission, "alice")
        elapsed = (time.perf_counter() - started) * 1000
        self.assertEqual((store.reads, store.writes), (1, 1))
        print(f" choices benchmark: 12 exercises/36 rows, 1 read + 1 write, local {elapsed:.2f}ms")

    def test_finish_handler_saves_new_basis_and_retries_without_duplicate(self):
        source = ast.parse((Path(__file__).resolve().parents[1] / "serve.py").read_text(encoding="utf-8-sig"))
        names = {"finish_with_progression_choices", "make_submission_record", "remember_submission",
                 "state_has_submission", "evaluate_and_update", "format_weight", "duplicate_finish_response"}
        store = FakeStore()
        store.connected = True
        ns = dict(NS)
        ns.update(time=time, jsonify=lambda value: value, now_iso=lambda: "now",
                  validate_choices=validate_choices, atomic_save=atomic_save,
                  sheets_store=lambda: store, sheets_connected=lambda: True,
                  target_muscle=lambda name: "팔", save_state=lambda *args, **kwargs: None,
                  invalidate_state_cache=lambda username: None)
        exec(compile(ast.Module(body=[n for n in source.body if isinstance(n, ast.FunctionDef)
                                     and n.name in names], type_ignores=[]), "finish", "exec"), ns)
        state = {"logs": [], "gyms": []}
        self.logs[-1]["reps"] = 6
        body = {"submissionId": "session-1", "progressionChoices": {self.name: self.choice}}
        args = (body, state, self.logs, [], {self.name: self.ex},
                {"2": []}, "alice", "", time.perf_counter())
        result = ns["finish_with_progression_choices"](*args)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["progressionChoicesSaved"])
        self.assertIn("8kg × 11", result["progressReport"][0])
        self.assertEqual(len(state["logs"]), 3)
        result = ns["finish_with_progression_choices"](*args)
        self.assertTrue(result["duplicate"])
        self.assertEqual(len(state["logs"]), 3)


if __name__ == "__main__":
    unittest.main()
