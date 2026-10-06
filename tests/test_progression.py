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
             "set_succeeded", "next_progression_sets", "apply_progression", "normalize_logs", "duplicate_exercise_sets", "workout_sessions_from_logs", "routine_exercise_lookup", "workout_exercise_lookup"}
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
        self.assertEqual([s["reps"] for s in result], [13, 13, 13])
        self.assertEqual([s["weight"] for s in result], [20.1] * 3)
        self.assertEqual([s["targetReps"] for s in result], [13, 13, 13])

    def test_ohp_legacy_success_below_range_keeps_entire_session(self):
        self.ex.update(name="오버헤드 프레스 (OHP - 바벨)", rpeTarget=7)
        for log, reps in zip(self.logs, [10, 9, 8]):
            log.update(exercise=self.ex["name"], reps=reps, targetReps=reps, rpe=7)
        self.assertEqual([s["reps"] for s in self.targets()], [10, 10, 10])

    def test_save_cannot_use_corrupt_below_range_target(self):
        ex = {**self.ex, "repsRange": "12-15"}
        log = {**self.logs[0], "targetReps": 11, "reps": 11, "completed": True}
        saved = NS["normalize_logs"]([log], 2, 1, "Day 2", {ex["name"]: ex}, username="sjoh")[0]
        self.assertEqual((saved["status"], saved["targetReps"]), ("FAIL", 12))

    def test_weight_uses_interval_from_actual_weight(self):
        for log in self.logs:
            log.update(reps=12, targetReps=12)
        self.assertEqual([(s["weight"], s["reps"]) for s in self.targets()], [(11.5, 10)] * 3)

    def test_failures_retry_original_targets_not_actual_performance(self):
        for change in ({"weight": 7.5}, {"reps": 10}, {"rpe": 9}, {"completed": False}):
            with self.subTest(change=change):
                logs = copy.deepcopy(self.logs)
                logs[2].update(change, status="FAIL")
                result = NS["next_progression_sets"](self.ex, logs, self.gym)
                for log, target in zip(logs, result):
                    self.assertEqual((target["weight"], target["reps"], target["rpe"]), (9, 11, 8))
                    self.assertEqual((target["targetWeight"], target["targetReps"]), (9, 11))

    def test_failure_within_range_retries_higher_original_target(self):
        for log in self.logs:
            log.update(targetReps=12)
        result = self.targets()
        self.assertEqual([s["reps"] for s in result], [12, 12, 12])
        self.assertEqual([s["rpe"] for s in result], [8, 8, 8])

    def test_uneven_corrupt_targets_retry_one_exercise_target(self):
        self.ex.update(name="오버헤드 프레스 (OHP - 바벨)", repsRange="6-8", rpeTarget=8)
        for log, reps in zip(self.logs, [8, 5, 5]):
            log.update(exercise=self.ex["name"], weight=30, targetWeight=30,
                       reps=reps, targetReps=reps, rpe=8)
        result = self.targets()
        self.assertEqual([(s["weight"], s["reps"]) for s in result], [(30, 8)] * 3)

    def test_retry_below_original_target_saves_fail(self):
        log = {**self.logs[2], "weight": 7.5, "completed": True, "targetRpe": 8}
        saved = NS["normalize_logs"]([log], 2, 1, "Day 2", username="sjoh")[0]
        self.assertEqual((saved["status"], saved["weight"], saved["targetWeight"]), ("FAIL", 7.5, 9))

    def test_last_set_does_not_override_other_sets(self):
        self.logs[0].update(weight=10)
        self.assertEqual([s["weight"] for s in self.targets()], [9, 9, 9])

    def test_success_uses_weight_achieved_by_every_set(self):
        self.ex.update(name="힙 어브덕션", repsRange="12-15")
        for log in self.logs:
            log.update(exercise=self.ex["name"], weight=97.5, targetWeight=38.5,
                       reps=12, targetReps=12)
        self.assertEqual([(s["weight"], s["reps"]) for s in self.targets()], [(97.5, 13)] * 3)
        self.logs[0]["weight"] = 100
        self.assertEqual([s["weight"] for s in self.targets()], [97.5] * 3)
        for log in self.logs:
            log.update(reps=15, targetReps=15)
        self.assertEqual([(s["weight"], s["reps"]) for s in self.targets()], [(100, 12)] * 3)
        self.logs[2].update(reps=14, status="FAIL")
        self.assertEqual([(s["weight"], s["reps"]) for s in self.targets()], [(38.5, 15)] * 3)

    def test_assisted_success_uses_assistance_achieved_by_every_set(self):
        self.ex.update(name="머신 풀업", repsRange="8-10")
        for log, weight in zip(self.logs, [25, 30, 30]):
            log.update(exercise=self.ex["name"], weight=weight, targetWeight=40,
                       reps=9, targetReps=9)
        self.assertEqual([(s["weight"], s["reps"]) for s in self.targets()], [(30, 10)] * 3)
        for log in self.logs:
            log.update(reps=10, targetReps=10)
        self.assertEqual([(s["weight"], s["reps"]) for s in self.targets()], [(25, 8)] * 3)
        self.logs[2].update(rpe=9, status="FAIL")
        self.assertEqual([(s["weight"], s["reps"]) for s in self.targets()], [(40, 10)] * 3)

    def test_latest_session_separates_days_names_and_repeated_sessions(self):
        lookup = NS["latest_exercise_logs"]
        for regular, single in [("레그 익스텐션", "싱글 레그 레그 익스텐션"),
                                ("레그 컬", "싱글 레그 라잉 레그 컬")]:
            logs = [{**self.logs[0], "exercise": name, "weight": weight, "day": day}
                    for name, weight, day in [(single, 15, "Day 3"), (regular, 40, "Day 3"),
                                              (single, 80, "Day 1")]]
            self.assertEqual(lookup(logs, 2, single, "Day 3")[0]["weight"], 15)
            self.assertEqual(lookup(logs, 2, regular, "Day 3")[0]["weight"], 40)
        for use_ids in [True, False]:
            logs = [{**log, "status": status, "submissionId": str(i) if use_ids else ""}
                    for i, status in enumerate(["FAIL", "SUCCESS"]) for log in self.logs]
            latest = lookup(logs, 2, self.ex["name"], "Day 2")
            self.assertEqual(len(NS["workout_sessions_from_logs"](logs)), 2)
            self.assertEqual(len(latest), 3)
            self.assertTrue(all(log["status"] == "SUCCESS" for log in latest))
            self.assertEqual(NS["next_progression_sets"](self.ex, latest, self.gym)[0]["reps"], 12)

    def test_replacement_save_uses_current_slot_not_another_day(self):
        routines = {"2": [
            {"id": "Day 1", "exercises": [{"name": "교체 운동", "repsRange": "15-20", "sets": 3, "rpeTarget": 9}]},
            {"id": "Day 3", "exercises": [{"name": "원래 운동", "repsRange": "6-8", "sets": 3, "rpeTarget": 7}]}]}
        defs = NS["workout_exercise_lookup"](routines, 2, "Day 3",
                [{"originalExercise": "원래 운동", "exercise": "교체 운동"}])
        self.assertEqual(defs["교체 운동"]["repsRange"], "6-8")
        raw = {**self.logs[0], "exercise": "교체 운동", "reps": 6, "targetReps": 6, "rpe": 7, "targetRpe": 7}
        saved = NS["normalize_logs"]([raw], 2, 1, "Day 3", defs)[0]
        self.assertEqual((saved["targetReps"], saved["status"]), (6, "SUCCESS"))

    def test_duplicate_exercises_rejected_but_distinct_names_allowed(self):
        check = NS["duplicate_exercise_sets"]
        self.assertFalse(check(self.logs))
        self.assertTrue(check(self.logs + self.logs))
        self.assertFalse(check(self.logs + [{**log, "exercise": "다른 운동"} for log in self.logs]))

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
        self.assertEqual(ex["progressionSets"][2]["weight"], 9)
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
