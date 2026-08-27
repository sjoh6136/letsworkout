import copy
import os
import re
import sys
import types
from pathlib import Path

os.environ["GOOGLE_SHEETS_ENABLED"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeFlask:
    def __init__(self, *_args, **_kwargs):
        pass

    def after_request(self, handler):
        return handler

    def before_request(self, handler):
        return handler

    def route(self, *_args, **_kwargs):
        def decorator(handler):
            return handler
        return decorator


flask_stub = types.ModuleType("flask")
flask_stub.Flask = FakeFlask
flask_stub.g = types.SimpleNamespace()
flask_stub.jsonify = lambda *args, **kwargs: {"args": args, "kwargs": kwargs}
flask_stub.make_response = lambda value=None, *_args, **_kwargs: value
flask_stub.request = types.SimpleNamespace(
    method="GET",
    path="/",
    headers={},
    cookies={},
    is_secure=False,
)
flask_stub.send_from_directory = lambda *_args, **_kwargs: None
sys.modules.setdefault("flask", flask_stub)

from serve import (  # noqa: E402
    DEFAULT_GYM,
    GoogleSheetsStore,
    cardio_log_already_saved,
    routine_position_for_split,
    user_tab_title,
)


def col_index(name):
    value = 0
    for char in name:
        value = value * 26 + ord(char) - 64
    return value


class FakeWorksheet:
    def __init__(self, title):
        self.title = title
        self.rows = []
        self.append_calls = []

    def get(self, range_name):
        match = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d*)", range_name)
        if not match:
            raise AssertionError(f"unsupported range {range_name}")

        start_col = col_index(match.group(1))
        start_row = int(match.group(2))
        end_col = col_index(match.group(3))
        end_row = int(match.group(4)) if match.group(4) else len(self.rows)

        if start_row > len(self.rows):
            return []

        result = []
        for row_index in range(start_row - 1, min(end_row, len(self.rows))):
            row = self.rows[row_index]
            padded = row + [""] * max(0, end_col - len(row))
            result.append(padded[start_col - 1:end_col])
        return result

    def update(self, values, range_name):
        match = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", range_name)
        if not match:
            raise AssertionError(f"unsupported update range {range_name}")

        start_row = int(match.group(2))
        if start_row == 1 and len(values) > 1:
            self.rows = copy.deepcopy(values)
            return

        while len(self.rows) < start_row:
            self.rows.append([])
        for offset, row in enumerate(values):
            target = start_row - 1 + offset
            if target >= len(self.rows):
                self.rows.append([])
            self.rows[target] = copy.deepcopy(row)

    def append_row(self, row, **_kwargs):
        self.append_calls.append(_kwargs)
        self.rows.append(copy.deepcopy(row))

    def append_rows(self, rows, **_kwargs):
        self.append_calls.append(_kwargs)
        self.rows.extend(copy.deepcopy(rows))

    def clear(self):
        self.rows = []


class FakeStore(GoogleSheetsStore):
    def __init__(self):
        self.connected = True
        self.error = None
        self.spreadsheet = None
        self._worksheets = {}
        self._ensured_user_tabs = set()

    def worksheet(self, title, rows=100, cols=20):
        if title not in self._worksheets:
            self._worksheets[title] = FakeWorksheet(title)
        return self._worksheets[title]

    def worksheet_if_exists(self, title):
        return self._worksheets.get(title)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def make_log(username, exercise):
    return {
        "date": "2026-08-24",
        "username": username,
        "split": 2,
        "week": 1,
        "day": "Day 1",
        "exercise": exercise,
        "setNo": 1,
        "weight": 100,
        "reps": 8,
        "rpe": 8,
        "status": "SUCCESS",
        "targetWeight": 100,
        "targetReps": 8,
    }


def main():
    store = FakeStore()
    store.ensure_user_tabs("sjoh")

    shared_titles = {
        store.SETTINGS_TAB,
        store.LOGS_TAB,
        store.GYM_SETTINGS_TAB,
        store.REPLACEMENTS_TAB,
        store.SUBMISSIONS_TAB,
        store.ROUTINE_PROGRESS_TAB,
        store.CARDIO_LOGS_TAB,
    }
    assert_equal(set(store._worksheets), shared_titles, "shared tab creation")
    assert not any("__" in title for title in store._worksheets), "user-scoped tabs must not be created"

    store.save_one_rms({"squat": 111, "bench": 77, "deadlift": 155, "ohp": 60, "activeSplit": 2}, "sjoh")
    store.save_one_rms({"squat": 1, "bench": 2, "deadlift": 3, "ohp": 4, "activeSplit": 5}, "park")
    assert_equal(store.load_one_rms("sjoh")["squat"], 111.0, "1RM sjoh filter")
    assert_equal(store.load_one_rms("park")["bench"], 2.0, "1RM park filter")

    gym = copy.deepcopy(DEFAULT_GYM)
    gym["id"] = "gym-sjoh"
    gym["name"] = "우리동네 헬스장"
    store.save_gyms(gym["id"], [gym], "sjoh")
    other_gym = copy.deepcopy(DEFAULT_GYM)
    other_gym["id"] = "gym-park"
    other_gym["name"] = "다른 헬스장"
    store.save_gyms(other_gym["id"], [other_gym], "park")
    active_gym_id, gyms = store.load_gyms("sjoh")
    assert_equal(active_gym_id, "gym-sjoh", "gym active id filter")
    assert_equal(gyms[0]["name"], "우리동네 헬스장", "gym name filter")

    store.append_logs([make_log("sjoh", "벤치프레스")], "sjoh")
    store.append_logs([make_log("park", "스쿼트")], "park")
    assert_equal(len(store.load_logs("sjoh")), 1, "workout logs filter count")
    assert_equal(store.load_logs("sjoh")[0]["exercise"], "벤치프레스", "workout logs filter exercise")
    assert_equal(store._worksheets[store.LOGS_TAB].rows[0], store.LOG_HEADER, "Workout_Logs header")
    assert_equal(store._worksheets[store.LOGS_TAB].rows[1][1], "sjoh", "Workout_Logs username column")
    assert "table_range" not in store._worksheets[store.LOGS_TAB].append_calls[-1], "Workout_Logs append must use sheet bottom"

    out_of_order_logs = [
        {**make_log("sjoh", "백 스쿼트"), "date": "2026-08-25", "day": "Day 1"},
        {**make_log("sjoh", "백 스쿼트"), "date": "2026-08-18", "day": "Day 1"},
        {**make_log("sjoh", "데드리프트"), "date": "2026-08-21", "day": "Day 3"},
        {**make_log("sjoh", "벤치프레스"), "date": "2026-08-24", "day": "Day 4"},
    ]
    position = routine_position_for_split({"logs": out_of_order_logs}, 2, {"baselineLogCount": 1}, 4)
    assert_equal(position["lastCompletedDay"], "Day 1", "routine position uses chronological last session")
    assert_equal(position["nextRecommendedDay"], "Day 2", "routine recommendation after out-of-order Day 1")

    store.append_replacements([{
        "date": "2026-08-24",
        "split": 2,
        "week": 1,
        "day": "Day 1",
        "originalExercise": "벤치프레스",
        "exercise": "덤벨 벤치프레스",
        "setCount": 3,
        "bestWeight": 30,
        "bestReps": 8,
        "estimatedOneRm": 38,
        "volume": 720,
        "summary": "30kg x 8",
        "submissionId": "sub-sjoh",
        "createdAt": "2026-08-24T12:00:00",
    }], "sjoh")
    assert_equal(len(store.load_replacements("sjoh")), 1, "replacement filter")
    assert_equal(len(store.load_replacements("park")), 0, "replacement cross-user isolation")

    store.append_submission({"id": "same", "date": "2026-08-24", "split": 2, "week": 1, "day": "Day 1", "logCount": 1, "createdAt": "now"}, "sjoh")
    store.append_submission({"id": "park-only", "date": "2026-08-24", "split": 2, "week": 1, "day": "Day 1", "logCount": 1, "createdAt": "now"}, "park")
    assert "same" in store.load_submission_ids("sjoh"), "submission id for sjoh"
    assert "park-only" not in store.load_submission_ids("sjoh"), "submission id cross-user isolation"

    store.save_routine_progress({"2": {"version": "ver.2", "blockLength": 12, "baselineLogCount": 3, "startedAt": "start"}}, "sjoh")
    store.save_routine_progress({"2": {"version": "ver.1", "blockLength": 12, "baselineLogCount": 99, "startedAt": "start"}}, "park")
    assert_equal(store.load_routine_progress("sjoh")["2"]["version"], "ver.2", "routine progress filter")
    assert_equal(store.load_routine_progress("park")["2"]["baselineLogCount"], 99, "routine progress preserves other user")

    store.append_cardio_log({"date": "2026-08-24", "activity": "유산소", "durationSeconds": 1200, "submissionId": "cardio-sjoh", "createdAt": "now"}, "sjoh")
    store.append_cardio_log({"date": "2026-08-24", "activity": "유산소", "durationSeconds": 600, "submissionId": "cardio-park", "createdAt": "now"}, "park")
    assert_equal(len(store.load_cardio_logs("sjoh")), 1, "cardio logs filter")
    assert_equal(store.load_cardio_logs("sjoh")[0]["durationSeconds"], 1200, "cardio duration")
    assert "table_range" not in store._worksheets[store.CARDIO_LOGS_TAB].append_calls[-1], "Cardio_Logs append must use sheet bottom"
    assert not cardio_log_already_saved(
        {"cardioLogs": [{"date": "2026-08-24", "username": "sjoh", "activity": "유산소", "durationSeconds": 1200, "submissionId": "same-cardio-id"}]},
        {"date": "2026-08-25", "username": "sjoh", "activity": "유산소", "durationSeconds": 1200, "submissionId": "same-cardio-id"},
    ), "same cardio submission id on a different date must not block a new row"
    assert cardio_log_already_saved(
        {"cardioLogs": [{"date": "2026-08-24", "username": "sjoh", "activity": "유산소", "durationSeconds": 1200, "submissionId": "same-cardio-id"}]},
        {"date": "2026-08-24", "username": "sjoh", "activity": "유산소", "durationSeconds": 1200, "submissionId": "same-cardio-id"},
    ), "same cardio submission id on the same date remains idempotent"

    legacy_logs_title = user_tab_title(store.LOGS_TAB, "legacy")
    store._worksheets[legacy_logs_title] = FakeWorksheet(legacy_logs_title)
    store._worksheets[legacy_logs_title].rows = [
        store.LOG_HEADER,
        ["2026-08-23", "legacy", 2, 1, "Day 1", "레그 프레스", 1, 100, 10, 8, "SUCCESS", 100, 10],
    ]
    assert_equal(len(store.load_logs("legacy")), 0, "legacy workout logs are ignored after migration")

    legacy_settings_title = user_tab_title(store.SETTINGS_TAB, "legacy")
    store._worksheets[legacy_settings_title] = FakeWorksheet(legacy_settings_title)
    store._worksheets[legacy_settings_title].rows = [
        ["Squat", "Bench", "Deadlift", "OHP", "ActiveSplit"],
        [200, 120, 220, 60, 2],
    ]
    assert_equal(store.load_one_rms("legacy")["deadlift"], 160.0, "legacy 1RM settings are ignored after migration")

    print("shared table store checks ok")


if __name__ == "__main__":
    main()
