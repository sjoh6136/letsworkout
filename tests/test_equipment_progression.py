import unittest
from test_progression import NS
from workout_log_edits import edited_row


class EquipmentProgressionTests(unittest.TestCase):
    def test_named_equipment_respects_gym_steps(self):
        gym = {"dumbbellInterval": 2, "availablePlates": [2.5, 5], "barbellWeight": 20}
        self.assertFalse(NS["is_barbell_exercise"]("고블릿 스쿼트"))
        for weight in (8, 24):
            self.assertEqual(NS["resolve_equipment_weight"]("고블릿 스쿼트", weight, gym)[0], weight)
        self.assertEqual(NS["progression_target_weight"]("고블릿 스쿼트", 20, gym), 26)
        self.assertEqual(NS["resolve_equipment_weight"]("해머 컬", 12, {**gym, "dumbbellInterval": 2.5})[0], 12.5)
        for name in ("EZ바 컬", "EZ바 스컬크러셔"):
            self.assertEqual(NS["progression_target_weight"](name, 20, gym), 25)
            self.assertEqual(NS["progression_target_weight"](name, 20, {**gym, "availablePlates": [1.25, 2.5]}), 22.5)
            self.assertEqual(NS["resolve_equipment_weight"](name, 10, gym)[0], 10)

    def test_bodyweight_save_reload_edit_and_progression(self):
        for name in ("체중 풀업", "체중 딥스", "친업"):
            ex = {"name": name, "sets": 3, "repsRange": "8-12", "rpeTarget": 8}
            logs = [dict(exercise=name, setNo=i, weight=0, targetWeight=0, reps=10,
                         targetReps=10, rpe=8, completed=True) for i in range(1, 4)]
            saved = NS["normalize_logs"](logs, 2, 1, "Day 2", {name: ex})
            self.assertTrue(all(x["status"] == "SUCCESS" for x in saved))
            reloaded = [{k: v for k, v in x.items() if k not in ("completed", "checked")} for x in saved]
            target = NS["next_progression_sets"](ex, reloaded, {})[0]
            self.assertEqual((target["weight"], target["reps"]), (0, 11))
            for log in reloaded:
                log.update(reps=12, targetReps=12)
            target = NS["next_progression_sets"](ex, reloaded, {})[0]
            self.assertEqual((target["weight"], target["reps"]), (5, 8))
            reloaded[-1].update(rpe=0, status="FAIL")
            target = NS["next_progression_sets"](ex, reloaded, {})[0]
            self.assertEqual((target["weight"], target["reps"]), (0, 12))
            row = ["2026-10-28", "test", "2", "1", "Day 2", name, "1", "0", "10", "8", "FAIL", "0", "10"]
            self.assertEqual(edited_row(row, dict(weight=0, reps=10, rpe=8, completed=True))[10], "SUCCESS")
            self.assertEqual(edited_row(row, dict(weight=0, reps=10, rpe=8, completed=False))[10], "FAIL")
            self.assertFalse(NS["weight_meets_target"]({"exercise": name, "weight": -1, "targetWeight": 0}))

    def test_reps_and_failed_retries_do_not_reround(self):
        for name in ("고블릿 스쿼트", "해머 컬", "EZ바 컬", "EZ바 스컬크러셔"):
            ex = {"name": name, "sets": 3, "repsRange": "8-12", "rpeTarget": 8}
            logs = [dict(exercise=name, setNo=i, weight=9, targetWeight=9, reps=10,
                         targetReps=10, rpe=8, status="SUCCESS") for i in range(1, 4)]
            gym = {"dumbbellInterval": 2.5, "availablePlates": [2.5]}
            self.assertEqual(NS["next_progression_sets"](ex, logs, gym)[0]["weight"], 9)
            logs[-1].update(reps=5, status="FAIL")
            target = NS["next_progression_sets"](ex, logs, gym)[0]
            self.assertEqual((target["weight"], target["reps"]), (9, 10))


if __name__ == "__main__":
    unittest.main()
