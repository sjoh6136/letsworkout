import ast
import copy
import runpy
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ast.parse((ROOT / "serve.py").read_text(encoding="utf-8-sig"))
store_class = next(n for n in SOURCE.body if isinstance(n, ast.ClassDef) and n.name == "GoogleSheetsStore")
selected = [n for n in store_class.body if isinstance(n, ast.Assign) or
            isinstance(n, ast.FunctionDef) and n.name in {"ensure_shared_workout_tabs", "ensure_user_tabs", "sheet_actor"}]
namespace = {"normalize_username": lambda name: str(name).lower()}
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name="Store", bases=[], keywords=[], body=selected, decorator_list=[])], type_ignores=[])), "store", "exec"), namespace)

class SavePathsTests(unittest.TestCase):
    def store(self):
        store = namespace["Store"]()
        store._shared_workout_tabs_ready = False
        store._ensured_user_tabs = set()
        store.worksheet = lambda title, **kwargs: title
        return store

    def test_shared_headers_checked_once_across_users(self):
        store = self.store()
        calls = []
        store.ensure_header = lambda *args: calls.append(args)
        store.ensure_shared_workout_tabs()
        self.assertEqual(len(calls), 7)
        store.ensure_user_tabs("alice")
        store.ensure_user_tabs("bob")
        self.assertEqual(len(calls), 7)

    def test_failed_header_check_does_not_mark_ready(self):
        store = self.store()
        def fail(*args):
            raise OSError("Sheets unavailable")
        store.ensure_header = fail
        with self.assertRaises(OSError):
            store.ensure_shared_workout_tabs()
        self.assertFalse(store._shared_workout_tabs_ready)
        calls = []
        store.ensure_header = lambda *args: calls.append(args)
        store.ensure_shared_workout_tabs()
        self.assertEqual(len(calls), 7)
        self.assertTrue(store._shared_workout_tabs_ready)

    def test_adjusted_session_feedback_matches_next_routine(self):
        ns=runpy.run_path(str(ROOT / "tests/test_progression.py"))["NS"]
        ns.update(sheets_connected=lambda:False,target_muscle=lambda name:"등")
        nodes=[n for n in SOURCE.body if isinstance(n,ast.FunctionDef) and n.name in {"evaluate_and_update","format_weight"}]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),"feedback","exec"),ns)
        ex=dict(name="리버스 그립 랫 풀다운",sets=3,repsRange="6-8",rpeTarget=8)
        raw=[dict(exercise=ex["name"],setNo=i,weight=60,targetWeight=65,reps=6,targetReps=6,rpe=8,completed=True) for i in [1,2,3]]
        logs=ns["normalize_logs"](raw,2,1,"Day 4",{ex["name"]:ex})
        result=ns["evaluate_and_update"]({"logs":[],"gyms":[]},logs,2,1,"Day 4",{"2":[]},{ex["name"]:ex})
        self.assertEqual((result["status"],result["completedSets"],result["totalVolume"]),("SUCCESS",3,1080))
        self.assertIn("60kg × 7회",result["progressReport"][0])
        self.assertEqual(ns["next_progression_sets"](ex,logs,{})[0]["reps"],7)

    def test_feedback_does_not_mutate_state(self):
        ns = runpy.run_path(str(ROOT / "tests/test_progression.py"))["NS"]
        ns.update(sheets_connected=lambda:False, target_muscle=lambda name:"하체")
        nodes = [n for n in SOURCE.body if isinstance(n, ast.FunctionDef) and n.name in {"evaluate_and_update", "format_weight"}]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),"feedback","exec"),ns)
        ex = {"name":"힙 어브덕션","sets":3,"repsRange":"12-15","rpeTarget":8}
        logs = [{"exercise":ex["name"],"split":2,"week":1,"day":"Day 3","setNo":i,
                 "weight":97.5,"targetWeight":38.5,"reps":12,"targetReps":12,"rpe":8,"status":"SUCCESS"} for i in [1,2,3]]
        state = {"oneRms":{"squat":150},"logs":[],"gyms":[]}
        before = copy.deepcopy(state)
        result = ns["evaluate_and_update"](state,logs,2,1,"Day 3",{"2":[]},{ex["name"]:ex})
        self.assertEqual(state,before)
        self.assertIn("97.5kg × 13",result["progressReport"][0])

if __name__ == "__main__":
    unittest.main()
