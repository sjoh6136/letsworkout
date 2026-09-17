import ast
import copy
import json
import math
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ast.parse((ROOT / "serve.py").read_text(encoding="utf-8-sig"))
FUNCTIONS = {"as_float", "as_int", "sheet_bool", "parse_reps_range", "clamp_target_reps",
             "active_gym", "is_barbell_exercise", "round_to_step", "resolve_equipment_weight",
             "get_increment", "is_assisted_machine_exercise", "weight_meets_target",
             "progression_target_weight", "latest_exercise_logs", "log_checked",
             "set_succeeded", "next_progression_sets", "apply_progression", "normalize_logs"}
DEFS = json.loads((ROOT / "data/exercise_definitions.json").read_text(encoding="utf-8-sig"))
NS = {"copy": copy, "math": math, "re": re,
      "ASSISTED_MACHINE_EXERCISES": {"머신 딥스", "머신 풀업"},
      "load_exercise_definitions": lambda: {"large": DEFS["large_muscles"], "small": DEFS["small_muscles"]},
      "DEFAULT_GYM": {}, "today_iso": lambda: "2026-09-17", "normalize_username": lambda value: value.lower()}
# Run the production pure functions without Flask or external Sheets access.
exec(compile(ast.Module(body=[n for n in SOURCE.body if isinstance(n, ast.FunctionDef)
                             and n.name in FUNCTIONS], type_ignores=[]), "serve.py", "exec"), NS)


class ProgressionTests(unittest.TestCase):
    def setUp(self):
        self.ex = {"name": "덤벨 슈피네이티드 컬", "sets": 3, "repsRange": "10-12", "rpeTarget": 8}
        self.gym = {"dumbbellInterval": 2.5, "availablePlates": [2.5, 5, 10]}
        self.logs = [{"exercise": self.ex["name"], "split": 2, "day": "Day 2", "date": "2026-09-16",
                      "setNo": i, "weight": 9, "targetWeight": 9, "reps": 11, "targetReps": 11,
                      "rpe": 8, "status": "SUCCESS"} for i in range(1, 4)]

    def targets(self):
        return NS["next_progression_sets"](self.ex, self.logs, self.gym)

    def test_reps_only_preserves_nine_kg(self):
        self.assertEqual([(s["weight"], s["reps"]) for s in self.targets()], [(9, 12)] * 3)

    def test_fly_13_11_11_legacy_success_must_not_progress(self):
        self.ex.update(name="케이블 플라이", repsRange="12-15")
        for log, reps in zip(self.logs, [13, 11, 11]):
            log.update(exercise=self.ex["name"], weight=20.1, targetWeight=20.1,
                       reps=reps, targetReps=reps)
        result = self.targets()
        self.assertEqual([s["reps"] for s in result], [13, 11, 11])
        self.assertEqual([s["weight"] for s in result], [20.1] * 3)
        self.assertEqual([s["targetReps"] for s in result], [13, 12, 12])

    def test_ohp_legacy_success_below_range_keeps_entire_session(self):
        self.ex.update(name="오버헤드 프레스 (OHP - 바벨)", rpeTarget=7)
        for log, reps in zip(self.logs, [10, 9, 8]):
            log.update(exercise=self.ex["name"], reps=reps, targetReps=reps, rpe=7)
        self.assertEqual([s["reps"] for s in self.targets()], [10, 9, 8])

    def test_save_cannot_use_corrupt_below_range_target(self):
        ex = {**self.ex, "repsRange": "12-15"}
        log = {**self.logs[0], "targetReps": 11, "reps": 11, "completed": True}
        saved = NS["normalize_logs"]([log], 2, 1, "Day 2", {ex["name"]: ex}, username="sjoh")[0]
        self.assertEqual((saved["status"], saved["targetReps"]), ("FAIL", 12))

    def test_weight_uses_interval_from_actual_weight(self):
        for log in self.logs:
            log.update(reps=12, targetReps=12)
        self.assertEqual([(s["weight"], s["reps"]) for s in self.targets()], [(11.5, 10)] * 3)

    def test_failures_preserve_inputs_and_original_targets(self):
        for change in ({"weight": 7.5}, {"reps": 10}, {"rpe": 9}, {"completed": False}):
            with self.subTest(change=change):
                logs = copy.deepcopy(self.logs)
                logs[2].update(change, status="FAIL")
                result = NS["next_progression_sets"](self.ex, logs, self.gym)
                for log, target in zip(logs, result):
                    self.assertEqual((target["weight"], target["reps"], target["rpe"]),
                                     (log["weight"], log["reps"], log["rpe"]))
                    self.assertEqual((target["targetWeight"], target["targetReps"]), (9, 11))

    def test_retry_below_original_target_saves_fail(self):
        log = {**self.logs[2], "weight": 7.5, "completed": True, "targetRpe": 8}
        saved = NS["normalize_logs"]([log], 2, 1, "Day 2", username="sjoh")[0]
        self.assertEqual((saved["status"], saved["weight"], saved["targetWeight"]), ("FAIL", 7.5, 9))

    def test_last_set_does_not_override_other_sets(self):
        self.logs[0].update(weight=10)
        self.assertEqual([s["weight"] for s in self.targets()], [10, 9, 9])

    def test_missing_sets_do_not_progress(self):
        result = NS["next_progression_sets"](self.ex, self.logs[:2], self.gym)
        self.assertEqual([s["reps"] for s in result], [11, 11])

    def test_barbell_uses_paired_plates(self):
        self.assertEqual(NS["progression_target_weight"]("플랫 바벨 벤치프레스", 100,
                                                        {"availablePlates": [5, 10]}), 110)

    def test_assistance_decreases_and_zero_is_valid(self):
        for name in ("머신 딥스", "머신 풀업"):
            self.assertEqual(NS["progression_target_weight"](name, 40, self.gym), 35)
            self.assertEqual(NS["progression_target_weight"](name, 2.5, self.gym), 0)
            self.assertTrue(NS["weight_meets_target"]({"exercise": name, "weight": 0, "targetWeight": 0}))

    def test_routine_keeps_failure_inputs_and_does_not_mutate_source(self):
        self.logs[2].update(weight=7.5, status="FAIL")
        state = {"oneRms": {}, "gyms": [self.gym], "logs": self.logs}
        routine = {"2": [{"id": "Day 2", "exercises": [self.ex]}]}
        ex = NS["apply_progression"](routine, state)["2"][0]["exercises"][0]
        self.assertEqual(ex["targetWeight"], 9)
        self.assertEqual(ex["progressionSets"][2]["weight"], 7.5)
        self.assertNotIn("progressionSets", self.ex)

    def test_every_routine_exercise_keeps_weight_during_reps_progression(self):
        routines = json.loads((ROOT / "data/routines.json").read_text(encoding="utf-8-sig"))
        versions = json.loads((ROOT / "data/two_day_versions.json").read_text(encoding="utf-8-sig"))
        for days in [*routines.values(), *versions.values()]:
            for day in days:
                for ex in day["exercises"]:
                    lo, hi = NS["parse_reps_range"](ex.get("repsRange"))
                    if lo == hi:
                        continue
                    logs = [{**self.logs[0], "exercise": ex["name"], "setNo": i,
                             "reps": lo, "targetReps": lo, "rpe": ex["rpeTarget"]}
                            for i in range(1, ex["sets"] + 1)]
                    targets = NS["next_progression_sets"](ex, logs, self.gym)
                    with self.subTest(name=ex["name"], day=day["id"]):
                        self.assertTrue(all(s["weight"] == 9 and s["reps"] == lo + 1 for s in targets))


if __name__ == "__main__":
    unittest.main()
