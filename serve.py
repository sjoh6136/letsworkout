from __future__ import annotations

import copy
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, jsonify, request, send_from_directory


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "src" / "main" / "resources" / "static"
DATA_DIR = ROOT / "data"
STATE_DIR = Path(os.environ.get("APP_DATA_DIR", ROOT / "data")).resolve()
ROUTINES_FILE = DATA_DIR / "routines.json"
EXERCISE_DEFINITIONS_FILE = DATA_DIR / "exercise_definitions.json"
STATE_FILE = STATE_DIR / "app_state.json"
GYM_SETTINGS_FILE = ROOT / "gym_settings.json"
APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Seoul")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN")

DEFAULT_ONE_RMS = {
    "squat": 150.0,
    "bench": 100.0,
    "deadlift": 160.0,
    "ohp": 60.0,
    "activeSplit": 5,
}

DEFAULT_GYM = {
    "id": "gym_default",
    "name": "우리동네 헬스장",
    "barbellWeight": 20.0,
    "availablePlates": [20.0, 15.0, 10.0, 5.0, 2.5, 1.25],
    "dumbbellInterval": 2.0,
    "machineProgressionMap": {},
}


app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")


@app.after_request
def add_deployment_headers(response):
    if ALLOWED_ORIGIN:
        response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    return response


def load_json(path: Path, fallback):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        print(f"[warn] failed to read {path.name}: {exc}")
    return copy.deepcopy(fallback)


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def today_iso():
    try:
        tz = ZoneInfo(APP_TIMEZONE)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date().isoformat()


def load_legacy_gyms():
    legacy = load_json(GYM_SETTINGS_FILE, {})
    gyms = legacy.get("gyms") if isinstance(legacy, dict) else None
    if isinstance(gyms, list) and gyms:
        return legacy.get("activeGymId") or gyms[0].get("id"), gyms
    return DEFAULT_GYM["id"], [copy.deepcopy(DEFAULT_GYM)]


def load_state():
    state = load_json(STATE_FILE, None)
    if not isinstance(state, dict):
        active_gym_id, gyms = load_legacy_gyms()
        state = {
            "oneRms": copy.deepcopy(DEFAULT_ONE_RMS),
            "logs": [],
            "activeGymId": active_gym_id,
            "gyms": gyms,
        }

    state.setdefault("oneRms", copy.deepcopy(DEFAULT_ONE_RMS))
    state.setdefault("logs", [])
    state.setdefault("gyms", [copy.deepcopy(DEFAULT_GYM)])
    state.setdefault("activeGymId", state["gyms"][0]["id"] if state["gyms"] else DEFAULT_GYM["id"])

    for key, value in DEFAULT_ONE_RMS.items():
        state["oneRms"].setdefault(key, value)

    if not state["gyms"]:
        state["gyms"].append(copy.deepcopy(DEFAULT_GYM))
        state["activeGymId"] = DEFAULT_GYM["id"]

    return state


def save_state(state) -> None:
    save_json(STATE_FILE, state)


def load_routines():
    routines = load_json(ROUTINES_FILE, {})
    if not isinstance(routines, dict):
        return {}
    return routines


def load_exercise_definitions():
    definitions = load_json(EXERCISE_DEFINITIONS_FILE, {})
    return {
        "large": set(definitions.get("large_muscles") or []),
        "small": set(definitions.get("small_muscles") or []),
    }


def as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_reps_range(reps_range):
    if not reps_range:
        return 8, 12

    parts = re.split(r"[~-]", str(reps_range))
    try:
        if len(parts) >= 2:
            return int(parts[0].strip()), int(parts[1].strip())
        value = int(parts[0].strip())
        return value, value
    except (TypeError, ValueError):
        return 8, 12


def active_gym(state):
    gyms = state.get("gyms") or []
    active_id = state.get("activeGymId")
    for gym in gyms:
        if gym.get("id") == active_id:
            return gym
    return gyms[0] if gyms else copy.deepcopy(DEFAULT_GYM)


def is_barbell_exercise(name):
    lower = (name or "").lower()
    if "덤벨" in lower or "dumbbell" in lower:
        return False
    tokens = ["바벨", "barbell", "벤치프레스", "스쿼트", "데드리프트", "오버헤드 프레스", "ohp"]
    return any(token in lower for token in tokens)


def round_to_step(value, step):
    if step <= 0:
        return value
    return round(value / step) * step


def resolve_equipment_weight(exercise_name, target_weight, gym):
    if target_weight <= 0:
        return target_weight, False, target_weight

    lower = (exercise_name or "").lower()
    if "덤벨" in lower or "dumbbell" in lower:
        interval = as_float(gym.get("dumbbellInterval"), 2.0) or 2.0
        adjusted = round_to_step(target_weight, interval)
        return adjusted, adjusted != target_weight, target_weight

    if not is_barbell_exercise(exercise_name):
        return target_weight, False, target_weight

    bar = as_float(gym.get("barbellWeight"), 20.0)
    plates = [as_float(p) for p in gym.get("availablePlates", []) if as_float(p) > 0]
    if not plates:
        return target_weight, False, target_weight

    min_plate = min(plates)
    adjusted = bar if target_weight <= bar else bar + round_to_step((target_weight - bar) / 2.0, min_plate) * 2.0
    return adjusted, adjusted != target_weight, target_weight


def get_increment(exercise_name):
    definitions = load_exercise_definitions()
    name = (exercise_name or "").strip()
    if name in definitions["large"]:
        return 5.0
    if name in definitions["small"]:
        return 2.5

    lower = name.lower()
    if any(token in lower for token in ["스쿼트", "squat", "데드리프트", "deadlift", "벤치프레스", "bench", "레그 프레스", "leg press"]):
        return 5.0
    return 2.5


def one_rm_for(one_rms, lift_type):
    if lift_type in {"squat", "bench", "deadlift", "ohp"}:
        return as_float(one_rms.get(lift_type), DEFAULT_ONE_RMS[lift_type])
    return 100.0


def latest_exercise_logs(logs, split, exercise_name):
    matching = [log for log in logs if log.get("split") == split and log.get("exercise") == exercise_name and log.get("date")]
    if not matching:
        return []
    latest_date = max(log["date"] for log in matching)
    return [log for log in matching if log.get("date") == latest_date]


def set_succeeded(log, rpe_target):
    return (
        str(log.get("status", "")).upper() == "SUCCESS"
        and as_int(log.get("reps")) >= as_int(log.get("targetReps"))
        and as_float(log.get("rpe")) <= rpe_target
    )


def routine_exercise_lookup(routines, split):
    lookup = {}
    for day in routines.get(str(split), []):
        for ex in day.get("exercises", []):
            lookup[ex.get("name")] = ex
    return lookup


def apply_progression(routines, state):
    one_rms = state["oneRms"]
    logs = state.get("logs", [])
    gym = active_gym(state)
    result = copy.deepcopy(routines)

    for split_key, days in result.items():
        split = as_int(split_key)
        for day in days:
            for ex in day.get("exercises", []):
                name = ex.get("name")
                min_reps, max_reps = parse_reps_range(ex.get("repsRange"))
                rpe_target = as_float(ex.get("rpeTarget"), 8.5)
                previous = latest_exercise_logs(logs, split, name)

                if previous:
                    previous_sorted = sorted(previous, key=lambda log: as_int(log.get("setNo")))
                    prev_last = previous_sorted[-1]
                    prev_weight = as_float(prev_last.get("weight"), as_float(ex.get("defaultWeight")))
                    prev_target_reps = as_int(prev_last.get("targetReps"), min_reps)

                    if all(set_succeeded(log, rpe_target) for log in previous_sorted):
                        if prev_target_reps < max_reps:
                            target_weight = prev_weight
                            target_reps = prev_target_reps + 1
                        else:
                            target_weight = prev_weight + get_increment(name)
                            target_reps = min_reps
                    else:
                        target_weight = prev_weight
                        target_reps = prev_target_reps

                    ex["previousLog"] = {
                        "date": previous_sorted[0].get("date"),
                        "weight": prev_last.get("weight"),
                        "reps": prev_last.get("reps"),
                        "sets": len(previous_sorted),
                        "rpe": prev_last.get("rpe"),
                    }
                    by_set = {as_int(log.get("setNo")): log for log in previous_sorted}
                    ex["previousSets"] = [
                        {"weight": by_set[i].get("weight"), "reps": by_set[i].get("reps")} if i in by_set else None
                        for i in range(1, as_int(ex.get("sets")) + 1)
                    ]
                else:
                    if ex.get("coreLift") and ex.get("coreLiftType"):
                        target_weight = round_to_step(one_rm_for(one_rms, ex.get("coreLiftType")) * as_float(ex.get("intensity")), 2.5)
                    else:
                        target_weight = as_float(ex.get("defaultWeight"))
                    target_reps = min_reps
                    ex["previousLog"] = None
                    ex["previousSets"] = []

                adjusted, was_adjusted, raw = resolve_equipment_weight(name, target_weight, gym)
                ex["targetWeight"] = adjusted
                ex["targetReps"] = target_reps
                ex["plateAdjusted"] = was_adjusted
                if was_adjusted:
                    ex["rawTargetWeight"] = raw

    return result


def target_muscle(exercise_name):
    name = (exercise_name or "").lower()
    if any(token in name for token in ["벤치프레스", "bench", "플라이", "fly", "딥스", "dips"]):
        return "가슴"
    if any(token in name for token in ["로우", "row", "풀다운", "pulldown", "풀업", "pull-up", "pull up", "랫 풀"]):
        return "등"
    if any(token in name for token in ["스쿼트", "squat", "데드리프트", "deadlift", "루마니안", "런지", "레그", "leg", "카프", "calf", "복근", "크런치"]):
        return "하체"
    if any(token in name for token in ["오버헤드 프레스", "ohp", "숄더", "shoulder", "레터럴", "lateral", "페이스 풀", "face pull"]):
        return "어깨"
    if any(token in name for token in ["컬", "curl", "트라이셉스", "triceps", "푸시다운", "푸쉬다운", "pushdown"]):
        return "팔"
    return "기타"


def normalize_logs(raw_logs, split, week, day_id):
    today = today_iso()
    normalized = []
    for raw in raw_logs or []:
        log = dict(raw)
        log["date"] = log.get("date") or today
        log["split"] = split
        log["week"] = week
        log["day"] = day_id
        log["setNo"] = as_int(log.get("setNo"), 1)
        log["targetWeight"] = as_float(log.get("targetWeight"))
        log["weight"] = as_float(log.get("weight"))
        log["targetReps"] = as_int(log.get("targetReps"))
        log["reps"] = as_int(log.get("reps"))
        log["rpe"] = as_float(log.get("rpe"))
        checked_success = str(log.get("status", "")).upper() == "SUCCESS"
        log["status"] = "SUCCESS" if checked_success and log["reps"] >= log["targetReps"] else "FAIL"
        normalized.append(log)
    return normalized


def day_number(day_id):
    match = re.search(r"\d+", day_id or "")
    return int(match.group(0)) if match else 1


def evaluate_and_update(state, logs, split, week, day_id):
    routines = load_routines()
    exercise_defs = routine_exercise_lookup(routines, split)
    one_rms = state["oneRms"]

    logs_by_exercise = {}
    for log in logs:
        logs_by_exercise.setdefault(log.get("exercise"), []).append(log)

    progress_report = []
    all_sets_success = True
    has_failure = False
    total_rpe = 0.0
    rpe_count = 0
    lifted_core_types = set()

    for exercise_name, ex_logs in logs_by_exercise.items():
        ex_def = exercise_defs.get(exercise_name, {})
        min_reps, max_reps = parse_reps_range(ex_def.get("repsRange"))
        rpe_target = as_float(ex_def.get("rpeTarget"), 8.5)
        ex_all_success = all(set_succeeded(log, rpe_target) for log in ex_logs)

        if not ex_all_success:
            all_sets_success = False

        for log in ex_logs:
            if log["status"] != "SUCCESS":
                has_failure = True
            if log["rpe"] > 0:
                total_rpe += log["rpe"]
                rpe_count += 1

        prev_target_reps = as_int(ex_logs[-1].get("targetReps"), as_int(ex_def.get("targetReps"), min_reps))
        if ex_all_success:
            if prev_target_reps < max_reps:
                progress_report.append(f"🔼 {exercise_name}: 다음 목표 {prev_target_reps + 1}회")
            else:
                progress_report.append(f"⚡ {exercise_name}: 다음 목표 +{get_increment(exercise_name)}kg, {min_reps}회")

            core_type = ex_def.get("coreLiftType") if ex_def.get("coreLift") else None
            if core_type in {"squat", "bench", "deadlift", "ohp"}:
                lifted_core_types.add(core_type)
        else:
            progress_report.append(f"❄️ {exercise_name}: 유지")

    avg_rpe = total_rpe / rpe_count if rpe_count else 0.0

    if has_failure:
        status = "FAIL"
        feedback = f"⚠️ 목표를 채우지 못한 세트가 있습니다. 평균 RPE는 {avg_rpe:.1f}이고, 다음에는 같은 목표로 재도전합니다."
    else:
        for core_type in lifted_core_types:
            one_rms[core_type] = as_float(one_rms.get(core_type)) + 2.5
        status = "SUCCESS"
        if lifted_core_types:
            changed = ", ".join(f"{key.upper()} {one_rms[key]:.1f}kg" for key in sorted(lifted_core_types))
            feedback = f"🎉 목표와 RPE 기준을 만족했습니다. 핵심 리프트 1RM을 업데이트했습니다: {changed}"
        elif all_sets_success:
            feedback = "🎉 목표와 RPE 기준을 만족했습니다. 보조 운동은 다음 목표로 진행합니다."
        else:
            feedback = "훈련을 저장했습니다."

    updated_logs = state.get("logs", []) + logs
    weekly_muscle_sets = {"가슴": 0, "등": 0, "하체": 0, "어깨": 0, "팔": 0}
    for log in updated_logs:
        if log.get("split") == split and log.get("week") == week and log.get("status") == "SUCCESS":
            muscle = target_muscle(log.get("exercise"))
            if muscle in weekly_muscle_sets:
                weekly_muscle_sets[muscle] += 1

    return {
        "status": status,
        "feedback": feedback,
        "sheetsConnected": False,
        "totalVolume": sum(log["weight"] * log["reps"] for log in logs if log["status"] == "SUCCESS"),
        "completedSets": sum(1 for log in logs if log["status"] == "SUCCESS"),
        "totalSets": len(logs),
        "progressReport": progress_report,
        "weeklyMuscleSets": weekly_muscle_sets,
    }


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(app.static_folder, path)


@app.route("/api/workout/settings", methods=["GET", "POST"])
def workout_settings():
    state = load_state()
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        for key, default in DEFAULT_ONE_RMS.items():
            if key in body:
                state["oneRms"][key] = bool(body[key]) if isinstance(default, bool) else as_float(body[key], default)
        state["oneRms"]["activeSplit"] = as_int(state["oneRms"].get("activeSplit"), 5)
        save_state(state)
        return jsonify(state["oneRms"])

    return jsonify({"oneRms": state["oneRms"], "sheetsConnected": False})


@app.route("/api/workout/routine")
def workout_routine():
    state = load_state()
    return jsonify(apply_progression(load_routines(), state))


@app.route("/api/workout/status")
def workout_status():
    state = load_state()
    active_split = as_int(state["oneRms"].get("activeSplit"), 5)
    next_recommended = "Day 1"
    last_completed = None

    for log in reversed(state.get("logs", [])):
        if log.get("split") == active_split:
            last_num = day_number(log.get("day"))
            last_completed = f"Day {last_num}"
            next_num = last_num + 1 if last_num < active_split else 1
            next_recommended = f"Day {next_num}"
            break

    return jsonify({
        "sheetsConnected": False,
        "lastCompletedDay": last_completed,
        "nextRecommendedDay": next_recommended,
    })


@app.route("/api/workout/logs")
def workout_logs():
    return jsonify(load_state().get("logs", []))


@app.route("/api/workout/finish", methods=["POST"])
def workout_finish():
    state = load_state()
    body = request.get_json(silent=True) or {}
    split = as_int(body.get("split"), as_int(state["oneRms"].get("activeSplit"), 5))
    week = as_int(body.get("week"), 1)
    day_id = body.get("day") or "Day 1"
    logs = normalize_logs(body.get("logs", []), split, week, day_id)

    feedback = evaluate_and_update(state, logs, split, week, day_id)
    state["logs"].extend(logs)
    save_state(state)
    return jsonify(feedback)


@app.route("/api/workout/gyms", methods=["GET", "POST"])
def workout_gyms():
    state = load_state()
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        gym = {
            "id": f"gym_{int(time.time() * 1000)}",
            "name": (body.get("name") or "우리동네 헬스장").strip(),
            "barbellWeight": as_float(body.get("barbellWeight"), 20.0),
            "availablePlates": [as_float(p) for p in body.get("availablePlates", DEFAULT_GYM["availablePlates"])],
            "dumbbellInterval": as_float(body.get("dumbbellInterval"), 2.0),
            "machineProgressionMap": {},
        }
        state["gyms"].append(gym)
        state["activeGymId"] = gym["id"]
        save_state(state)
        return jsonify(gym)

    return jsonify({"activeGymId": state.get("activeGymId"), "gyms": state.get("gyms", [])})


@app.route("/api/workout/gyms/<gym_id>", methods=["PUT", "DELETE"])
def workout_gym_detail(gym_id):
    state = load_state()
    gyms = state.get("gyms", [])
    gym = next((item for item in gyms if item.get("id") == gym_id), None)

    if request.method == "DELETE":
        if len(gyms) <= 1 or gym is None:
            return jsonify({"success": False, "gyms": gyms})
        state["gyms"] = [item for item in gyms if item.get("id") != gym_id]
        if state.get("activeGymId") == gym_id:
            state["activeGymId"] = state["gyms"][0]["id"]
        save_state(state)
        return jsonify({"success": True, "gyms": state["gyms"]})

    if gym is None:
        return jsonify({"error": "gym not found"}), 404

    body = request.get_json(silent=True) or {}
    gym["name"] = (body.get("name") or gym["name"]).strip()
    gym["barbellWeight"] = as_float(body.get("barbellWeight"), gym.get("barbellWeight", 20.0))
    if "availablePlates" in body:
        gym["availablePlates"] = [as_float(p) for p in body["availablePlates"]]
    gym["dumbbellInterval"] = as_float(body.get("dumbbellInterval"), gym.get("dumbbellInterval", 2.0))
    save_state(state)
    return jsonify(gym)


@app.route("/api/workout/gyms/select/<gym_id>", methods=["POST"])
def workout_gym_select(gym_id):
    state = load_state()
    if any(gym.get("id") == gym_id for gym in state.get("gyms", [])):
        state["activeGymId"] = gym_id
        save_state(state)
        return jsonify({"success": True, "activeGym": active_gym(state)})
    return jsonify({"success": False, "activeGym": active_gym(state)})


@app.route("/api/workout/gyms/<gym_id>/reset-machine", methods=["POST"])
def workout_gym_reset_machine(gym_id):
    state = load_state()
    exercise = (request.args.get("exercise") or "").strip()
    for gym in state.get("gyms", []):
        if gym.get("id") == gym_id:
            machine_map = gym.setdefault("machineProgressionMap", {})
            if exercise:
                machine_map.pop(exercise, None)
            else:
                machine_map.clear()
            save_state(state)
            return jsonify({"success": True})
    return jsonify({"success": False}), 404


@app.route("/api/exercises")
def exercises():
    return jsonify(load_json(EXERCISE_DEFINITIONS_FILE, {}))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
