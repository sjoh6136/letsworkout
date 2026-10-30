"""Session-scoped progression choices. Workout_Logs A:M stays unchanged."""
import hashlib
import json
import math
import threading

TAB = "Workout_Progression_Choices"
HEADER = ["Username", "SubmissionId", "Date", "Split", "Week", "Day",
          "FirstLogRow", "LogCount", "ChoicesJson", "PayloadHash"]
LOCK = threading.Lock()


def number(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("유효한 목표 숫자를 입력해주세요.")
    return value


def validate_choices(raw, logs, definitions):
    """Only accept a complete, explicit baseline for each submitted exercise."""
    if not isinstance(raw, dict):
        raise ValueError("종목별 다음 루틴 설정이 필요합니다.")
    names = {log["exercise"] for log in logs}
    if set(raw) != names:
        raise ValueError("종목별 다음 루틴 설정을 다시 확인해주세요.")
    result = {}
    for name in names:
        item = raw[name]
        if not isinstance(item, dict) or item.get("mode") not in {"on", "off", "unchanged"}:
            raise ValueError("다음 루틴 반영 설정을 확인해주세요.")
        entry = {"mode": item["mode"]}
        for key in ("originalWeight", "originalReps", "weight", "reps"):
            value = number(item.get(key))
            if value < 0 or ("Reps" in key or key == "reps") and (value < 1 or not value.is_integer()):
                raise ValueError("목표 무게는 0 이상, 횟수는 1 이상의 정수로 입력해주세요.")
            entry[key] = value
        ex = definitions.get(name, {})
        entry["requiredSets"] = int(ex.get("sets") or 3)
        entry["rpeTarget"] = float(ex.get("rpeTarget") or 8)
        if entry["mode"] != "on":
            entry["weight"], entry["reps"] = entry["originalWeight"], entry["originalReps"]
        if entry["mode"] == "on" and entry["weight"] == 0 and name not in {
                "머신 딥스", "머신 풀업", "체중 풀업", "체중 딥스", "친업"}:
            raise ValueError(f"{name}: 새 기준 무게는 0보다 커야 합니다.")
        result[name] = entry
    return result


def session_choice(logs):
    if not logs or not all(isinstance(log.get("progressionChoice"), dict) for log in logs):
        return None
    choice = logs[0]["progressionChoice"]
    return choice if all(log["progressionChoice"] == choice for log in logs) else None


def choice_succeeded(choice, logs, weight_check):
    if choice["mode"] == "off" or len(logs) < choice["requiredSets"]:
        return False
    return all(
        (log.get("completed") is not False and log.get("checked") is not False)
        and 0 < float(log.get("rpe") or 0) <= choice["rpeTarget"]
        and int(log.get("reps") or 0) >= choice["reps"]
        and weight_check({**log, "targetWeight": choice["weight"]})
        for log in logs
    )


def attach_choices(logs, records, username):
    """Physical row mapping survives history edits and repeated same-day sessions."""
    by_row = {}
    for record in records:
        if record[0] != username:
            continue
        choices = json.loads(record[8])
        for row in range(int(record[6]), int(record[6]) + int(record[7])):
            by_row[row] = (record, choices)
    for log in logs:
        matched = by_row.get(log.get("sheetRow"))
        if not matched:
            continue
        record, choices = matched
        if (str(log.get("date")) != record[2] or str(log.get("split")) != record[3]
                or str(log.get("week")) != record[4] or log.get("day") != record[5]):
            raise ValueError("운동 기록과 다음 루틴 설정의 연결을 확인할 수 없습니다.")
        choice = choices.get(log.get("exercise"))
        if choice is None:
            raise ValueError("운동 종목의 다음 루틴 설정이 없습니다.")
        log["progressionChoice"] = choice
        log["submissionId"] = record[1]
    return logs


def choice_sheet(store):
    sheet = store.worksheet(TAB, rows=500, cols=len(HEADER))
    if not getattr(store, "_progression_choices_ready", False):
        store.ensure_header(sheet, "A1:J1", HEADER)
        store._progression_choices_ready = True
    return sheet


def load_choices(store, username):
    sheet = choice_sheet(store)
    return [[str(cell) for cell in row] for row in (sheet.get("A2:J") or [])
            if len(row) >= 10 and str(row[0]).strip().lower() == username]


def row_cells(values):
    return {"values": [{"userEnteredValue": {"stringValue": str(value)}} for value in values]}


def atomic_save(store, logs, choices, submission, username, replacements=None):
    """One read and one atomic batch write, independent of exercise count.

    Record the row range in the same transaction as the logs and submission marker.
    Recheck the same submission on a response loss before retrying.
    """
    with LOCK:
        metadata = choice_sheet(store)
        log_sheet = store.worksheet(store.LOGS_TAB, rows=1000, cols=13)
        markers = store.worksheet(store.SUBMISSIONS_TAB, rows=500, cols=8)
        rows = [[log.get(key, "") for key in
                 ("date", "username", "split", "week", "day", "exercise", "setNo",
                  "weight", "reps", "rpe", "status", "targetWeight", "targetReps")]
                for log in logs]
        digest = hashlib.sha256(json.dumps([rows, choices], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        snapshot = store.spreadsheet.values_batch_get(
            [f"'{store.LOGS_TAB}'!A:A", f"'{TAB}'!A2:J"])["valueRanges"]
        records = snapshot[1].get("values", [])
        for record in records:
            if len(record) >= 10 and record[0] == username and record[1] == submission["id"]:
                if record[9] != digest:
                    raise ValueError("이미 저장한 회차의 내용이 변경되었습니다. 기록 수정 기능을 사용해주세요.")
                return False
        first_row = len(snapshot[0].get("values", [])) + 1
        record = [username, submission["id"], submission["date"], submission["split"],
                  submission["week"], submission["day"], first_row, len(rows),
                  json.dumps(choices, ensure_ascii=False, sort_keys=True), digest]
        marker = [submission["id"], username, submission["date"], submission["split"],
                  submission["week"], submission["day"], len(rows), submission["createdAt"]]
        requests = [
            {"appendCells": {"sheetId": log_sheet.id, "rows": [row_cells(row) for row in rows], "fields": "userEnteredValue"}},
            {"appendCells": {"sheetId": metadata.id, "rows": [row_cells(record)], "fields": "userEnteredValue"}},
            {"appendCells": {"sheetId": markers.id, "rows": [row_cells(marker)], "fields": "userEnteredValue"}},
        ]
        if replacements:
            replacement_sheet = store.worksheet(store.REPLACEMENTS_TAB, rows=500, cols=15)
            replacement_rows = [[item.get(key, "") for key in
                                 ("date", "split", "week", "day", "originalExercise", "exercise",
                                  "setCount", "bestWeight", "bestReps", "estimatedOneRm", "volume",
                                  "summary", "submissionId", "createdAt")] + [username]
                                for item in replacements]
            requests.append({"appendCells": {"sheetId": replacement_sheet.id,
                                             "rows": [row_cells(row) for row in replacement_rows],
                                             "fields": "userEnteredValue"}})
        try:
            store.spreadsheet.batch_update({"requests": requests})
        except Exception:
            if not any(r[1] == submission["id"] and r[9] == digest for r in load_choices(store, username)):
                raise
        for index, log in enumerate(logs):
            log["sheetRow"] = first_row + index
            log["progressionChoice"] = choices[log["exercise"]]
        return True
