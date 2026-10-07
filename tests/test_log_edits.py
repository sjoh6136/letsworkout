import ast
from pathlib import Path
import copy
import unittest
from workout_log_edits import edit_saved_log, edited_row, row_version, EditConflict

ROW = ["2026-10-01", "alice", "2", "1", "Day 3", "힙 어브덕션", "1", "38.5", "12", "8", "SUCCESS", "38.5", "12"]
CHANGES = dict(weight=97.5, reps=12, rpe=8, completed=True)

class FakeSheet:
    def __init__(self, rows, audit=False):
        self.rows = copy.deepcopy(rows)
        self.audit = audit
        self.writes = 0
        self.fail = ""
    def get(self, span):
        return copy.deepcopy(self.rows if self.audit else [self.rows[int(span.split(":")[0][1:])-2]])
    def append_row(self, row, **kwargs):
        if self.fail: raise OSError("audit unavailable")
        self.rows.append(row)
    def update(self, values, range_name, **kwargs):
        if self.fail == "before": raise OSError("offline")
        assert range_name.startswith("H") and ":K" in range_name
        idx = int(range_name.split(":")[0][1:])-2
        self.rows[idx][7:11] = values[0]
        self.writes += 1
        if self.fail == "after": raise OSError("response lost")

class Store:
    LOGS_TAB = "Workout_Logs"
    def __init__(self):
        self.logs = FakeSheet([ROW, [*ROW[:1], "bob", *ROW[2:]]])
        self.audit = FakeSheet([], True)
    def worksheet(self, name, **kwargs):
        return self.logs if name == self.LOGS_TAB else self.audit
    def ensure_header(self, *args): pass

class LogEditTests(unittest.TestCase):
    def setUp(self): self.store = Store()
    def edit(self, **kwargs):
        args = dict(store=self.store, actor="alice", row_number=2,
                    expected_version=row_version(ROW), edit_id="first", changes=CHANGES,
                    target_rpe_for=lambda row:8)
        args.update(kwargs)
        return edit_saved_log(**args)
    def test_only_actual_columns_change_and_original_is_preserved(self):
        self.edit()
        after = self.store.logs.rows[0]
        self.assertEqual(after[:7], ROW[:7])
        self.assertEqual(after[11:], ROW[11:])
        self.assertEqual(after[7:11], ["97.5", "12", "8", "SUCCESS"])
        self.assertEqual(len(self.store.audit.rows), 1)
        self.assertIn('38.5', self.store.audit.rows[0][4])
        self.assertEqual(self.store.logs.rows[1][1], "bob")
    def test_reject_other_user_and_stale_versions(self):
        for args in [dict(row_number=3), dict(expected_version="stale")]:
            with self.assertRaises(EditConflict): self.edit(**args)
        self.assertEqual(self.store.logs.writes, 0)
    def test_retry_is_idempotent(self):
        self.edit(); self.edit()
        self.assertEqual(self.store.logs.writes, 1)
        self.assertEqual(len(self.store.audit.rows), 1)
        with self.assertRaises(EditConflict): self.edit(changes={**CHANGES,"reps":13})
    def test_undo_restores_original_and_has_history(self):
        result = self.edit()
        self.edit(expected_version=result["rowVersion"], edit_id="undo", undo=True)
        self.assertEqual(self.store.logs.rows[0], ROW)
        self.assertEqual(len(self.store.audit.rows), 2)
    def test_audit_failure_never_changes_original(self):
        self.store.audit.fail = "before"
        with self.assertRaises(OSError): self.edit()
        self.assertEqual(self.store.logs.rows[0], ROW)
    def test_write_failure_retries_same_revision(self):
        self.store.logs.fail = "before"
        with self.assertRaises(OSError): self.edit()
        self.store.logs.fail = ""
        self.edit()
        self.assertEqual(len(self.store.audit.rows), 1)
        self.assertEqual(self.store.logs.rows[0][7], "97.5")
    def test_response_loss_is_verified(self):
        self.store.logs.fail = "after"
        self.assertTrue(self.edit()["saved"])
    def test_newer_edit_blocks_old_retry(self):
        result=self.edit()
        self.edit(expected_version=result["rowVersion"],edit_id="second",changes={**CHANGES,"weight":100})
        with self.assertRaises(EditConflict): self.edit()
    def test_validation_and_rpe(self):
        for changes in [dict(weight=float("nan")),dict(reps=2.5),dict(rpe=11),dict(rpe=0),dict(completed="true")]:
            with self.assertRaises(ValueError): edited_row(ROW,{**CHANGES,**changes})
        self.assertEqual(edited_row(ROW,{**CHANGES,"rpe":9},8)[10], "FAIL")
        self.assertEqual(edited_row(ROW,{**CHANGES,"completed":False})[10], "FAIL")
        self.assertEqual(edited_row(ROW,{**CHANGES,"reps":5})[10], "FAIL")
    def test_log_references_keep_physical_rows_when_filtering_users(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/"serve.py").read_text(encoding="utf-8-sig"))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="GoogleSheetsStore")
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=="load_logs")
        scope={"row_version":row_version,"normalize_username":lambda x:str(x).lower()}
        exec(compile(ast.Module(body=[method],type_ignores=[]),"load_logs","exec"),scope)
        store=self.store
        store.sheet_actor=lambda username,user_id:username
        store.ensure_user_tabs=lambda *args:None
        store.parse_log_row=lambda row,actor:{"username":row[1]}
        store.logs.get=lambda span:[ROW,[*ROW[:1],"bob",*ROW[2:]],ROW]
        logs=scope["load_logs"](store,"alice","")
        self.assertEqual([log["sheetRow"] for log in logs],[2,4])
        self.assertEqual(logs[0]["rowVersion"],row_version(ROW))

    def test_assisted_weights_are_reversed(self):
        row=ROW[:];row[5]="머신 풀업";row[11]="40"
        self.assertEqual(edited_row(row,{**CHANGES,"weight":35})[10], "SUCCESS")
        self.assertEqual(edited_row(row,{**CHANGES,"weight":45})[10], "FAIL")

if __name__ == "__main__": unittest.main()
