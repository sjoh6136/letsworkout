"""Edit one owned Sheets log row without moving rows or changing A-M."""
import hashlib
import json
import math
import threading
from datetime import datetime, timezone

_EDIT_LOCK = threading.Lock()
AUDIT_TAB = "Workout_Log_Edits"
AUDIT_HEADER = ["EditId", "Username", "LogRow", "ChangedAt", "Before", "After", "Action"]

class EditConflict(ValueError):
    pass


def canonical_row(row):
    return [str(value).strip() for value in (list(row) + [""] * 13)[:13]]


def row_version(row):
    return hashlib.sha256(json.dumps(canonical_row(row), ensure_ascii=False).encode()).hexdigest()


def edited_row(row, changes, target_rpe=8):
    before = canonical_row(row)
    values = {}
    for key in ("weight", "reps", "rpe"):
        try:
            value = float(changes[key])
        except (KeyError, ValueError, TypeError):
            raise ValueError("무게, 횟수, RPE를 숫자로 입력해주세요.")
        if not math.isfinite(value) or value < 0:
            raise ValueError("0 이상의 유효한 값을 입력해주세요.")
        values[key] = value
    if not values["reps"].is_integer() or values["rpe"] > 10:
        raise ValueError("횟수는 정수, RPE는 0–10으로 입력해주세요.")
    if not isinstance(changes.get("completed"), bool):
        raise ValueError("완료 여부를 선택해주세요.")
    if changes["completed"] and values["rpe"] <= 0:
        raise ValueError("완료한 세트의 RPE를 입력해주세요.")
    target_weight = float(before[11] or before[7] or 0)
    target_reps = int(float(before[12] or before[8] or 0))
    assisted = before[5] in {"머신 딥스", "머신 풀업"}
    weight_ok = values["weight"] <= target_weight if assisted else values["weight"] >= target_weight
    success = (changes["completed"] and weight_ok and values["reps"] > 0
               and values["reps"] >= target_reps and 0 < values["rpe"] <= target_rpe)
    after = before[:]
    after[7:11] = [f'{values["weight"]:g}', str(int(values["reps"])),
                   f'{values["rpe"]:g}', "SUCCESS" if success else "FAIL"]
    return after


def edit_saved_log(store, actor, row_number, expected_version, edit_id, changes,
                   target_rpe_for, undo=False):
    if row_number < 2 or not edit_id or len(edit_id) > 100:
        raise ValueError("수정할 기록을 다시 선택해주세요.")
    with _EDIT_LOCK:
        sheet = store.worksheet(store.LOGS_TAB, rows=1000, cols=13)
        current_rows = sheet.get(f"A{row_number}:M{row_number}") or []
        current = canonical_row(current_rows[0]) if current_rows else []
        if not current or current[1].lower() != actor or not current[0]:
            raise EditConflict("본인의 기록을 찾을 수 없습니다. 새로고침해주세요.")
        audit = store.worksheet(AUDIT_TAB, rows=500, cols=7)
        store.ensure_header(audit, "A1:G1", AUDIT_HEADER)
        revisions = [row for row in (audit.get("A2:G") or [])
                     if len(row) >= 7 and str(row[1]).lower() == actor
                     and str(row[2]) == str(row_number)]
        existing = next((r for r in revisions if r[0] == edit_id), None)
        if existing:
            before, after = json.loads(existing[4]), json.loads(existing[5])
            if expected_version != row_version(before) or existing[6] != ("undo" if undo else "edit"):
                raise EditConflict("수정 요청이 변경되었습니다. 기록을 다시 열어주세요.")
            if not undo and edited_row(before, changes, target_rpe_for(before)) != after:
                raise EditConflict("같은 수정 요청의 내용이 변경되었습니다. 기록을 다시 열어주세요.")
            if row_version(current) == row_version(after):
                return {"saved": True, "rowVersion": row_version(after)}
            if row_version(current) != row_version(before):
                raise EditConflict("이후 수정된 기록이 있습니다. 새로고침해주세요.")
        else:
            if row_version(current) != expected_version:
                raise EditConflict("기록이 변경되었습니다. 다시 열어 수정해주세요.")
            before = current
            if undo:
                previous = next((r for r in reversed(revisions)
                                 if row_version(json.loads(r[5])) == expected_version), None)
                if not previous:
                    raise EditConflict("되돌릴 수정 이력이 없습니다.")
                after = canonical_row(json.loads(previous[4]))
            else:
                after = edited_row(before, changes, target_rpe_for(before))
            if before == after:
                return {"saved": True, "rowVersion": expected_version}
            # Persist the recovery copy before changing the original row.
            audit.append_row([edit_id, actor, row_number, datetime.now(timezone.utc).isoformat(),
                              json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False),
                              "undo" if undo else "edit"], value_input_option="RAW")
        try:
            sheet.update(values=[after[7:11]], range_name=f"H{row_number}:K{row_number}", value_input_option="RAW")
        except Exception:
            verified = sheet.get(f"A{row_number}:M{row_number}") or []
            if not verified or row_version(verified[0]) != row_version(after):
                raise
        return {"saved": True, "rowVersion": row_version(after)}
