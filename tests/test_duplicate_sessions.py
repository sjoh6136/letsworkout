import ast
import unittest
from pathlib import Path

source = ast.parse((Path(__file__).resolve().parents[1] / "serve.py").read_text(encoding="utf-8-sig"))
names = {"as_int", "as_float", "log_duplicate_key", "workout_logs_already_saved"}
ns = {}
exec(compile(ast.Module(body=[n for n in source.body if isinstance(n, ast.FunctionDef)
                             and n.name in names], type_ignores=[]), "serve.py", "exec"), ns)


def session(reps, sid=""):
    return [dict(date="2026-10-28", split=2, week=1, day="Day 2", exercise="레그 컬",
                 setNo=i, weight=30, reps=r, rpe=8, status="SUCCESS",
                 targetWeight=30, targetReps=8, submissionId=sid)
            for i, r in enumerate(reps, 1)]


class DuplicateSessionTests(unittest.TestCase):
    def test_never_combine_sessions(self):
        for ids in [("a", "b"), ("", "")]:
            old = session([10, 8, 8], ids[0]) + session([8, 10, 10], ids[1])
            self.assertFalse(ns["workout_logs_already_saved"]({"logs": old}, session([10, 10, 10], "new")))

    def test_identical_session_still_rejected(self):
        for sid in ("a", ""):
            old = session([10, 8, 8], sid) + session([8, 10, 10], sid)
            self.assertTrue(ns["workout_logs_already_saved"]({"logs": old}, session([8, 10, 10], "retry")))

    def test_subset_is_not_identical_session(self):
        old = session([10, 10, 10])
        self.assertFalse(ns["workout_logs_already_saved"]({"logs": old}, old[:2]))
        self.assertFalse(ns["workout_logs_already_saved"]({"logs": old}, []))

    def test_other_days_do_not_match(self):
        old = session([10, 10, 10])
        new = [{**row, "day": "Day 4"} for row in old]
        self.assertFalse(ns["workout_logs_already_saved"]({"logs": old}, new))


if __name__ == "__main__":
    unittest.main()
