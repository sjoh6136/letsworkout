from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, g, jsonify, make_response, request, send_from_directory


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "src" / "main" / "resources" / "static"
DATA_DIR = ROOT / "data"
STATE_DIR = Path(os.environ.get("APP_DATA_DIR", ROOT / "data")).resolve()
ROUTINES_FILE = DATA_DIR / "routines.json"
TWO_DAY_VERSIONS_FILE = DATA_DIR / "two_day_versions.json"
EXERCISE_DEFINITIONS_FILE = DATA_DIR / "exercise_definitions.json"
ROUTINE_PROGRESS_FILE = STATE_DIR / "routine_progress.json"
STATE_FILE = STATE_DIR / "app_state.json"
AUTH_FILE = STATE_DIR / "auth_state.json"
GYM_SETTINGS_FILE = ROOT / "gym_settings.json"
APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Seoul")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN")
SPREADSHEET_ID = os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID", "1EZYNSFxd7iuEbKRCNSYyB-rVHz72TkS4TOAJcUxabBA")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON") or os.environ.get("GOOGLE_CREDENTIALS_JSON")
GOOGLE_CREDENTIALS_PATH = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GOOGLE_SHEETS_CREDENTIALS_PATH")
SHEETS_ENABLED = os.environ.get("GOOGLE_SHEETS_ENABLED", "true").lower() not in {"0", "false", "no"}
REQUIRE_SHEETS_FOR_FINISH = os.environ.get("REQUIRE_SHEETS_FOR_FINISH", "false").lower() in {"1", "true", "yes"}
AUTH_COOKIE_NAME = "lw_session"
AUTH_SESSION_DAYS = max(1, int(os.environ.get("AUTH_SESSION_DAYS", "180")))
AUTH_PASSWORD_ITERATIONS = 200_000
AUTH_CACHE_SECONDS = max(60, int(os.environ.get("AUTH_CACHE_SECONDS", str(12 * 60 * 60))))
STATE_CACHE_SECONDS = max(0, int(os.environ.get("STATE_CACHE_SECONDS", "180")))
APP_RELEASE = "2026-08-18-routine-progress-v1"
APP_BUILD_COMMIT = os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("SOURCE_VERSION") or ""
_SHEETS_STORE = None
_AUTH_SESSION_CACHE = {}
_STATE_CACHE = {}
_ROUTINES_CACHE = None
_TWO_DAY_VERSIONS_CACHE = None
_EXERCISE_DEFINITIONS_CACHE = None

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


app = Flask(__name__, static_folder=None)


@app.after_request
def add_deployment_headers(response):
    if ALLOWED_ORIGIN:
        response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    if request.method == "GET":
        content_type = response.headers.get("Content-Type", "")
        request_path = request.path or ""
        is_html_shell = (
            "text/html" in content_type
            or request_path in {"/", "/index.html"}
            or request_path.endswith(".html")
        )
        if is_html_shell:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
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


def sheet_float(value, default=0.0):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def sheet_int(value, default=0):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def sheet_json(value, default):
    if value in (None, ""):
        return copy.deepcopy(default)
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return copy.deepcopy(default)


def sheet_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes", "y", "active", "활성"}


def now_dt():
    try:
        tz = ZoneInfo(APP_TIMEZONE)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return datetime.now(tz)


def now_iso():
    return now_dt().isoformat(timespec="seconds")


def parse_iso_dt(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=now_dt().tzinfo)
        return parsed
    except ValueError:
        return None


def hash_password(password, salt_hex=None, iterations=AUTH_PASSWORD_ITERATIONS):
    salt_hex = salt_hex or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        bytes.fromhex(salt_hex),
        int(iterations),
    ).hex()
    return salt_hex, digest


def verify_password(password, salt_hex, expected_hash, iterations):
    if not password or not salt_hex or not expected_hash:
        return False
    _, digest = hash_password(password, salt_hex=salt_hex, iterations=int(iterations or AUTH_PASSWORD_ITERATIONS))
    return hmac.compare_digest(digest, str(expected_hash))


def session_token_hash(token):
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def public_user(user):
    if not user:
        return None
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "displayName": user.get("displayName") or user.get("username"),
    }


def normalize_username(username):
    return re.sub(r"\s+", "", str(username or "")).strip().lower()


def safe_username_suffix(username):
    username = normalize_username(username)
    suffix = re.sub(r"[^0-9a-zA-Z_-]+", "_", username).strip("_")
    return suffix[:40] or ""


def user_tab_title(base_title, username):
    suffix = safe_username_suffix(username)
    return f"{base_title}__{suffix}" if suffix else base_title


def active_users(users):
    return [user for user in users or [] if sheet_bool(user.get("active", True))]


def normalize_user(user):
    source = user if isinstance(user, dict) else {}
    username = normalize_username(source.get("username"))
    return {
        "id": str(source.get("id") or f"user_{int(time.time() * 1000)}").strip(),
        "username": username,
        "displayName": str(source.get("displayName") or username or "User").strip(),
        "passwordSalt": str(source.get("passwordSalt") or "").strip(),
        "passwordHash": str(source.get("passwordHash") or "").strip(),
        "iterations": sheet_int(source.get("iterations"), AUTH_PASSWORD_ITERATIONS),
        "active": sheet_bool(source.get("active", True)),
        "createdAt": str(source.get("createdAt") or now_iso()),
        "lastLoginAt": str(source.get("lastLoginAt") or ""),
    }


def normalize_session(session):
    source = session if isinstance(session, dict) else {}
    return {
        "tokenHash": str(source.get("tokenHash") or "").strip(),
        "userId": str(source.get("userId") or "").strip(),
        "username": normalize_username(source.get("username")),
        "createdAt": str(source.get("createdAt") or now_iso()),
        "expiresAt": str(source.get("expiresAt") or (now_dt() + timedelta(days=AUTH_SESSION_DAYS)).isoformat(timespec="seconds")),
        "revokedAt": str(source.get("revokedAt") or ""),
        "userAgent": str(source.get("userAgent") or "")[:200],
    }


def session_is_active(session):
    if not session or session.get("revokedAt"):
        return False
    expires_at = parse_iso_dt(session.get("expiresAt"))
    return bool(expires_at and expires_at > now_dt())


def clean_plates(plates):
    values = []
    for plate in plates or []:
        value = as_float(plate)
        if value > 0 and value not in values:
            values.append(value)
    values.sort(reverse=True)
    return values or copy.deepcopy(DEFAULT_GYM["availablePlates"])


def normalize_gym(gym):
    source = gym if isinstance(gym, dict) else {}
    gym_id = str(source.get("id") or f"gym_{int(time.time() * 1000)}").strip()
    name = str(source.get("name") or DEFAULT_GYM["name"]).strip() or DEFAULT_GYM["name"]
    machine_map = source.get("machineProgressionMap")
    if not isinstance(machine_map, dict):
        machine_map = {}

    return {
        "id": gym_id,
        "name": name,
        "barbellWeight": as_float(source.get("barbellWeight"), DEFAULT_GYM["barbellWeight"]),
        "availablePlates": clean_plates(source.get("availablePlates", DEFAULT_GYM["availablePlates"])),
        "dumbbellInterval": as_float(source.get("dumbbellInterval"), DEFAULT_GYM["dumbbellInterval"]) or DEFAULT_GYM["dumbbellInterval"],
        "machineProgressionMap": machine_map,
    }


def gym_signature(gym):
    normalized = normalize_gym(gym)
    return (
        normalized["name"].strip().lower(),
        round(normalized["barbellWeight"], 3),
        tuple(normalized["availablePlates"]),
        round(normalized["dumbbellInterval"], 3),
    )


def merge_machine_progression_maps(*maps):
    merged = {}
    for machine_map in maps:
        if not isinstance(machine_map, dict):
            continue
        for exercise, values in machine_map.items():
            name = str(exercise or "").strip()
            if not name:
                continue
            current = list(merged.get(name, []))
            incoming = values if isinstance(values, list) else [values]
            for value in incoming:
                if value not in current:
                    current.append(value)
            merged[name] = current
    return merged


def normalize_gym_state(active_gym_id, gyms):
    active_id = str(active_gym_id or "").strip()
    normalized = []
    seen = {}

    for gym in gyms or []:
        clean_gym = normalize_gym(gym)
        key = gym_signature(clean_gym)
        if key in seen:
            existing = normalized[seen[key]]
            merged_map = merge_machine_progression_maps(
                existing.get("machineProgressionMap"),
                clean_gym.get("machineProgressionMap"),
            )
            if clean_gym.get("id") == active_id:
                clean_gym["machineProgressionMap"] = merged_map
                normalized[seen[key]] = clean_gym
            else:
                existing["machineProgressionMap"] = merged_map
            continue
        seen[key] = len(normalized)
        normalized.append(clean_gym)

    if not normalized:
        normalized = [copy.deepcopy(DEFAULT_GYM)]

    if not any(gym.get("id") == active_id for gym in normalized):
        active_id = normalized[0]["id"]
    return active_id, normalized


class GoogleSheetsStore:
    SETTINGS_TAB = "Setting_1RM"
    LOGS_TAB = "Workout_Logs"
    GYM_SETTINGS_TAB = "Gym_Settings"
    REPLACEMENTS_TAB = "Workout_Replacements"
    SUBMISSIONS_TAB = "Workout_Submissions"
    ROUTINE_PROGRESS_TAB = "Routine_Progress"
    CARDIO_LOGS_TAB = "Cardio_Logs"
    USER_ACCOUNTS_TAB = "User_Accounts"
    USER_SESSIONS_TAB = "User_Sessions"
    SETTINGS_HEADER = ["Username", "Squat", "Bench", "Deadlift", "OHP", "ActiveSplit"]
    ROUTINE_PROGRESS_HEADER = ["Username", "Split", "Version", "BlockLength", "BaselineLogCount", "StartedAt", "UpdatedAt"]
    CARDIO_LOGS_HEADER = ["Date", "Username", "Activity", "DurationSeconds", "Memo", "SubmissionId", "CreatedAt"]
    GYM_SETTINGS_HEADER = [
        "Username",
        "Active",
        "GymId",
        "Name",
        "BarbellWeight",
        "AvailablePlates",
        "DumbbellInterval",
        "MachineProgressionMap",
    ]
    USER_ACCOUNTS_HEADER = [
        "UserId",
        "Username",
        "DisplayName",
        "PasswordSalt",
        "PasswordHash",
        "Iterations",
        "Active",
        "CreatedAt",
        "LastLoginAt",
    ]
    USER_SESSIONS_HEADER = [
        "TokenHash",
        "UserId",
        "Username",
        "CreatedAt",
        "ExpiresAt",
        "RevokedAt",
        "UserAgent",
    ]
    REPLACEMENTS_HEADER = [
        "Date",
        "Split",
        "Week",
        "Day",
        "OriginalExercise",
        "Exercise",
        "SetCount",
        "BestWeight",
        "BestReps",
        "EstimatedOneRm",
        "Volume",
        "Summary",
        "SubmissionId",
        "CreatedAt",
        "Username",
    ]
    SUBMISSIONS_HEADER = [
        "SubmissionId",
        "Username",
        "Date",
        "Split",
        "Week",
        "Day",
        "LogCount",
        "CreatedAt",
    ]
    LOG_HEADER = [
        "날짜",
        "사용자",
        "분할",
        "주차",
        "일차",
        "운동종목",
        "세트수",
        "무게(kg)",
        "횟수(reps)",
        "RPE",
        "상태(SUCCESS/FAIL)",
        "목표무게(kg)",
        "목표횟수(reps)",
    ]

    def __init__(self):
        self.connected = False
        self.error = None
        self.spreadsheet = None
        self._worksheets = {}
        self._ensured_user_tabs = set()
        if SHEETS_ENABLED:
            self.connect()

    def connect(self):
        try:
            import gspread

            if GOOGLE_CREDENTIALS_JSON:
                credentials = json.loads(GOOGLE_CREDENTIALS_JSON)
                client = gspread.service_account_from_dict(credentials)
            else:
                credential_candidates = []
                if GOOGLE_CREDENTIALS_PATH:
                    credential_candidates.append(Path(GOOGLE_CREDENTIALS_PATH))
                credential_candidates.extend([
                    ROOT / "credentials.json",
                    Path("/etc/secrets/credentials.json"),
                ])
                credentials_path = next((path for path in credential_candidates if path.exists()), None)
                if credentials_path is None:
                    raise FileNotFoundError("Google service account credentials were not found.")
                client = gspread.service_account(filename=str(credentials_path))

            self.spreadsheet = client.open_by_key(SPREADSHEET_ID)
            self.ensure_tabs()
            self.connected = True
            print(">>> Google Sheets connected. <<<")
        except Exception as exc:
            self.error = str(exc)
            print(f"[warn] Google Sheets unavailable, using local file storage: {exc}")

    def worksheet(self, title, rows=100, cols=20):
        import gspread

        if title in self._worksheets:
            return self._worksheets[title]

        try:
            worksheet = self.spreadsheet.worksheet(title)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = self.spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)
        self._worksheets[title] = worksheet
        return worksheet

    def worksheet_for_user(self, base_title, username="", rows=100, cols=20):
        return self.worksheet(user_tab_title(base_title, username), rows=rows, cols=cols)

    @staticmethod
    def column_name(index):
        name = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            name = chr(65 + remainder) + name
        return name or "A"

    @staticmethod
    def sheet_actor(username="", user_id=""):
        return normalize_username(username) or str(user_id or "").strip() or "__shared__"

    def log_actor_header(self, username=""):
        return "Username" if normalize_username(username) else "UserId"

    def log_header_for_user(self, username=""):
        return self.LOG_HEADER

    def replacements_header_for_user(self, username=""):
        return self.REPLACEMENTS_HEADER

    @staticmethod
    def header_matches(row, header):
        row = (row or []) + [""] * len(header)
        return [str(value).strip() for value in row[:len(header)]] == [str(value).strip() for value in header]

    def ensure_header(self, worksheet, range_name, header):
        values = worksheet.get(range_name)
        if not values or not self.header_matches(values[0], header):
            worksheet.update(values=[header], range_name=range_name)

    def ensure_tabs(self):
        user_accounts = self.worksheet(self.USER_ACCOUNTS_TAB, rows=20, cols=10)
        user_sessions = self.worksheet(self.USER_SESSIONS_TAB, rows=100, cols=8)

        self.ensure_header(user_accounts, "A1:I1", self.USER_ACCOUNTS_HEADER)
        self.ensure_header(user_sessions, "A1:G1", self.USER_SESSIONS_HEADER)
        self.ensure_shared_workout_tabs()

    def ensure_shared_workout_tabs(self):
        settings = self.worksheet(self.SETTINGS_TAB, rows=100, cols=6)
        logs = self.worksheet(self.LOGS_TAB, rows=1000, cols=13)
        gym_settings = self.worksheet(self.GYM_SETTINGS_TAB, rows=100, cols=8)
        replacements = self.worksheet(self.REPLACEMENTS_TAB, rows=500, cols=15)
        submissions = self.worksheet(self.SUBMISSIONS_TAB, rows=500, cols=8)
        routine_progress = self.worksheet(self.ROUTINE_PROGRESS_TAB, rows=100, cols=7)
        cardio_logs = self.worksheet(self.CARDIO_LOGS_TAB, rows=500, cols=7)

        self.ensure_header(settings, "A1:F1", self.SETTINGS_HEADER)
        self.ensure_header(logs, "A1:M1", self.LOG_HEADER)
        self.ensure_header(gym_settings, "A1:H1", self.GYM_SETTINGS_HEADER)
        self.ensure_header(replacements, "A1:O1", self.REPLACEMENTS_HEADER)
        self.ensure_header(submissions, "A1:H1", self.SUBMISSIONS_HEADER)
        self.ensure_header(routine_progress, "A1:G1", self.ROUTINE_PROGRESS_HEADER)
        self.ensure_header(cardio_logs, "A1:G1", self.CARDIO_LOGS_HEADER)

    def ensure_user_tabs(self, username="", user_id=""):
        actor = self.sheet_actor(username, user_id)
        if actor in self._ensured_user_tabs:
            return

        self.ensure_shared_workout_tabs()
        self._ensured_user_tabs.add(actor)

    def replace_actor_rows(self, worksheet, data_range, header, rows, actor, actor_index):
        actor = self.sheet_actor(actor)
        existing_rows = worksheet.get(data_range) or []
        width = len(header)
        kept_rows = []
        for row in existing_rows:
            normalized = (row + [""] * width)[:width]
            if not any(str(value).strip() for value in normalized):
                continue
            if normalize_username(normalized[actor_index]) == actor:
                continue
            kept_rows.append(normalized)

        output = [header] + rows
        if kept_rows:
            output.extend(kept_rows)

        worksheet.clear()
        end_column = self.column_name(width)
        worksheet.update(values=output, range_name=f"A1:{end_column}{len(output)}")

    def default_one_rms(self):
        return {
            "squat": DEFAULT_ONE_RMS["squat"],
            "bench": DEFAULT_ONE_RMS["bench"],
            "deadlift": DEFAULT_ONE_RMS["deadlift"],
            "ohp": DEFAULT_ONE_RMS["ohp"],
            "activeSplit": DEFAULT_ONE_RMS["activeSplit"],
        }

    def one_rms_from_row(self, row, offset=0):
        row = (row or []) + [""] * (offset + 5)
        return {
            "squat": sheet_float(row[offset], DEFAULT_ONE_RMS["squat"]),
            "bench": sheet_float(row[offset + 1], DEFAULT_ONE_RMS["bench"]),
            "deadlift": sheet_float(row[offset + 2], DEFAULT_ONE_RMS["deadlift"]),
            "ohp": sheet_float(row[offset + 3], DEFAULT_ONE_RMS["ohp"]),
            "activeSplit": sheet_int(row[offset + 4], DEFAULT_ONE_RMS["activeSplit"]),
        }

    def load_one_rms(self, username="", user_id=""):
        actor = self.sheet_actor(username, user_id)
        self.ensure_user_tabs(actor, user_id)
        settings = self.worksheet(self.SETTINGS_TAB, rows=100, cols=6)
        rows = settings.get("A2:F") or []
        for row in rows:
            row = (row or []) + [""] * 6
            if normalize_username(row[0]) == actor:
                return self.one_rms_from_row(row, offset=1)
        return self.default_one_rms()

    def save_one_rms(self, one_rms, username="", user_id=""):
        actor = self.sheet_actor(username, user_id)
        self.ensure_user_tabs(actor, user_id)
        settings = self.worksheet(self.SETTINGS_TAB, rows=100, cols=6)
        row = [
            actor,
            sheet_float(one_rms.get("squat"), DEFAULT_ONE_RMS["squat"]),
            sheet_float(one_rms.get("bench"), DEFAULT_ONE_RMS["bench"]),
            sheet_float(one_rms.get("deadlift"), DEFAULT_ONE_RMS["deadlift"]),
            sheet_float(one_rms.get("ohp"), DEFAULT_ONE_RMS["ohp"]),
            sheet_int(one_rms.get("activeSplit"), DEFAULT_ONE_RMS["activeSplit"]),
        ]
        self.replace_actor_rows(settings, "A2:F", self.SETTINGS_HEADER, [row], actor, 0)

    def load_routine_progress(self, username="", user_id=""):
        actor = self.sheet_actor(username, user_id)
        self.ensure_user_tabs(actor, user_id)
        progress_sheet = self.worksheet(self.ROUTINE_PROGRESS_TAB, rows=100, cols=7)
        values = progress_sheet.get("A2:G") or []
        progress = {}
        for row in values:
            row = row + [""] * 7
            if normalize_username(row[0]) != actor:
                continue
            split = str(sheet_int(row[1], 0))
            if split not in ROUTINE_SPLITS:
                continue
            progress[split] = {
                "version": str(row[2]).strip(),
                "blockLength": sheet_int(row[3], DEFAULT_ROUTINE_PROGRESS_ENTRY["blockLength"]),
                "baselineLogCount": sheet_int(row[4], DEFAULT_ROUTINE_PROGRESS_ENTRY["baselineLogCount"]),
                "startedAt": str(row[5]).strip(),
            }
        return progress

    def save_routine_progress(self, progress, username="", user_id=""):
        actor = self.sheet_actor(username, user_id)
        self.ensure_user_tabs(actor, user_id)
        progress_sheet = self.worksheet(self.ROUTINE_PROGRESS_TAB, rows=100, cols=7)
        rows = []
        updated_at = now_iso()
        for split in ROUTINE_SPLITS:
            entry = normalize_routine_progress_entry((progress or {}).get(split), split)
            rows.append([
                actor,
                split,
                entry.get("version", ""),
                as_int(entry.get("blockLength"), DEFAULT_ROUTINE_PROGRESS_ENTRY["blockLength"]),
                as_int(entry.get("baselineLogCount"), DEFAULT_ROUTINE_PROGRESS_ENTRY["baselineLogCount"]),
                entry.get("startedAt", ""),
                updated_at,
            ])
        self.replace_actor_rows(progress_sheet, "A2:G", self.ROUTINE_PROGRESS_HEADER, rows, actor, 0)

    def load_gyms(self, username="", user_id=""):
        actor = self.sheet_actor(username, user_id)
        self.ensure_user_tabs(actor, user_id)
        gym_settings = self.worksheet(self.GYM_SETTINGS_TAB, rows=100, cols=8)
        rows = gym_settings.get("A2:H")
        gyms = []
        active_gym_id = None

        for row in rows:
            row = row + [""] * 8
            if normalize_username(row[0]) != actor:
                continue
            if not row[2] and not row[3]:
                continue

            gym = normalize_gym({
                "id": row[2],
                "name": row[3],
                "barbellWeight": sheet_float(row[4], DEFAULT_GYM["barbellWeight"]),
                "availablePlates": sheet_json(row[5], DEFAULT_GYM["availablePlates"]),
                "dumbbellInterval": sheet_float(row[6], DEFAULT_GYM["dumbbellInterval"]),
                "machineProgressionMap": sheet_json(row[7], {}),
            })
            gyms.append(gym)
            if sheet_bool(row[1]):
                active_gym_id = gym["id"]

        if not gyms:
            return None, []
        return normalize_gym_state(active_gym_id, gyms)

    def save_gyms(self, active_gym_id, gyms, username="", user_id=""):
        actor = self.sheet_actor(username, user_id)
        self.ensure_user_tabs(actor, user_id)
        active_gym_id, gyms = normalize_gym_state(active_gym_id, gyms)
        gym_settings = self.worksheet(self.GYM_SETTINGS_TAB, rows=max(100, len(gyms) + 1), cols=8)
        rows = []
        for gym in gyms:
            rows.append([
                actor,
                "TRUE" if gym.get("id") == active_gym_id else "",
                gym.get("id", ""),
                gym.get("name", ""),
                as_float(gym.get("barbellWeight"), DEFAULT_GYM["barbellWeight"]),
                json.dumps(clean_plates(gym.get("availablePlates")), ensure_ascii=False),
                as_float(gym.get("dumbbellInterval"), DEFAULT_GYM["dumbbellInterval"]),
                json.dumps(gym.get("machineProgressionMap") or {}, ensure_ascii=False),
            ])
        self.replace_actor_rows(gym_settings, "A2:H", self.GYM_SETTINGS_HEADER, rows, actor, 0)
        return active_gym_id, gyms

    def load_users(self):
        accounts = self.worksheet(self.USER_ACCOUNTS_TAB, rows=20, cols=10)
        rows = accounts.get("A2:I")
        users = []
        for row in rows:
            row = row + [""] * 9
            if not row[0] and not row[1]:
                continue
            users.append(normalize_user({
                "id": row[0],
                "username": row[1],
                "displayName": row[2],
                "passwordSalt": row[3],
                "passwordHash": row[4],
                "iterations": row[5],
                "active": row[6],
                "createdAt": row[7],
                "lastLoginAt": row[8],
            }))
        return users

    def save_users(self, users):
        users = [normalize_user(user) for user in users or [] if normalize_username(user.get("username"))]
        accounts = self.worksheet(self.USER_ACCOUNTS_TAB, rows=max(20, len(users) + 1), cols=10)
        rows = [self.USER_ACCOUNTS_HEADER]
        for user in users:
            rows.append(self.user_row(user))
        accounts.clear()
        accounts.update(values=rows, range_name=f"A1:I{len(rows)}")
        return users

    def user_row(self, user):
        user = normalize_user(user)
        return [
            user.get("id", ""),
            user.get("username", ""),
            user.get("displayName", ""),
            user.get("passwordSalt", ""),
            user.get("passwordHash", ""),
            sheet_int(user.get("iterations"), AUTH_PASSWORD_ITERATIONS),
            "TRUE" if sheet_bool(user.get("active", True)) else "",
            user.get("createdAt", ""),
            user.get("lastLoginAt", ""),
        ]

    def append_user(self, user):
        user = normalize_user(user)
        accounts = self.worksheet(self.USER_ACCOUNTS_TAB, rows=20, cols=10)
        accounts.append_row(self.user_row(user), value_input_option="RAW", table_range="A1:I1")
        return user

    def load_sessions(self):
        sessions_sheet = self.worksheet(self.USER_SESSIONS_TAB, rows=100, cols=8)
        rows = sessions_sheet.get("A2:G")
        sessions = []
        for row in rows:
            row = row + [""] * 7
            if not row[0]:
                continue
            sessions.append(normalize_session({
                "tokenHash": row[0],
                "userId": row[1],
                "username": row[2],
                "createdAt": row[3],
                "expiresAt": row[4],
                "revokedAt": row[5],
                "userAgent": row[6],
            }))
        return sessions

    def save_sessions(self, sessions):
        sessions = [normalize_session(session) for session in sessions or [] if session.get("tokenHash")]
        sessions_sheet = self.worksheet(self.USER_SESSIONS_TAB, rows=max(100, len(sessions) + 1), cols=8)
        rows = [self.USER_SESSIONS_HEADER]
        for session in sessions:
            rows.append(self.session_row(session))
        sessions_sheet.clear()
        sessions_sheet.update(values=rows, range_name=f"A1:G{len(rows)}")
        return sessions

    def session_row(self, session):
        session = normalize_session(session)
        return [
            session.get("tokenHash", ""),
            session.get("userId", ""),
            session.get("username", ""),
            session.get("createdAt", ""),
            session.get("expiresAt", ""),
            session.get("revokedAt", ""),
            session.get("userAgent", ""),
        ]

    def append_session(self, session):
        session = normalize_session(session)
        sessions_sheet = self.worksheet(self.USER_SESSIONS_TAB, rows=100, cols=8)
        sessions_sheet.append_row(self.session_row(session), value_input_option="RAW", table_range="A1:G1")
        return session

    def revoke_session(self, token_hash, revoked_at):
        sessions_sheet = self.worksheet(self.USER_SESSIONS_TAB, rows=100, cols=8)
        rows = sessions_sheet.get("A2:A")
        for offset, row in enumerate(rows, start=2):
            if row and str(row[0]).strip() == token_hash:
                sessions_sheet.update(values=[[revoked_at]], range_name=f"F{offset}:F{offset}")
                return True
        return False

    def load_logs(self, username="", user_id=""):
        actor = self.sheet_actor(username, user_id)
        self.ensure_user_tabs(actor, user_id)
        logs = self.worksheet(self.LOGS_TAB, rows=1000, cols=13)
        rows = logs.get("A2:M") or []
        parsed = []
        for row in rows:
            log = self.parse_log_row(row, actor)
            if log and normalize_username(log.get("username")) == actor:
                parsed.append(log)
        return parsed

    def parse_log_row(self, row, username=""):
        row = [str(value).strip() for value in row]
        start = next((idx for idx, value in enumerate(row) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)), None)
        if start is None:
            return None
        row = row + [""] * (start + 14 - len(row))
        if len(row) - start < 12 or not row[start]:
            return None

        def is_number_cell(value):
            return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", str(value or "").strip()))

        has_new_actor_column = (
            len(row) - start >= 14
            and row[start + 1]
            and not is_number_cell(row[start + 1])
            and is_number_cell(row[start + 2])
        )
        if has_new_actor_column:
            actor = row[start + 1]
            base = start + 2
            submission_id = row[start + 13]
        else:
            actor = row[start + 13]
            base = start + 1
            submission_id = row[start + 12]
        actor_username = normalize_username("" if actor.startswith("user_") else actor) or normalize_username(username)
        return {
            "date": row[start],
            "split": sheet_int(row[base]),
            "week": sheet_int(row[base + 1], 1),
            "day": row[base + 2],
            "exercise": row[base + 3],
            "setNo": sheet_int(row[base + 4], 1),
            "weight": sheet_float(row[base + 5]),
            "reps": sheet_int(row[base + 6]),
            "rpe": sheet_float(row[base + 7]),
            "status": row[base + 8] or "FAIL",
            "targetWeight": sheet_float(row[base + 9], sheet_float(row[base + 5])),
            "targetReps": sheet_int(row[base + 10], sheet_int(row[base + 6])),
            "submissionId": submission_id,
            "username": actor_username,
            "userId": actor if actor.startswith("user_") else "",
        }

    def append_logs(self, logs, username="", user_id=""):
        if not logs:
            return True
        actor = self.sheet_actor(username, user_id)
        self.ensure_user_tabs(actor, user_id)
        worksheet = self.worksheet(self.LOGS_TAB, rows=1000, cols=13)
        rows = []
        for log in logs:
            rows.append([
                log.get("date", ""),
                normalize_username(log.get("username") or actor),
                log.get("split", ""),
                log.get("week", ""),
                log.get("day", ""),
                log.get("exercise", ""),
                log.get("setNo", ""),
                log.get("weight", ""),
                log.get("reps", ""),
                log.get("rpe", ""),
                log.get("status", ""),
                log.get("targetWeight", ""),
                log.get("targetReps", ""),
            ])
        worksheet.append_rows(rows, value_input_option="RAW", table_range="A1:M1")
        return True

    def load_cardio_logs(self, username="", user_id=""):
        actor = self.sheet_actor(username, user_id)
        self.ensure_user_tabs(actor, user_id)
        worksheet = self.worksheet(self.CARDIO_LOGS_TAB, rows=500, cols=7)
        rows = worksheet.get("A2:G") or []
        parsed = []
        for row in rows:
            row = [str(value).strip() for value in row]
            row = row + [""] * (7 - len(row))
            if not row[0] or normalize_username(row[1]) != actor:
                continue
            parsed.append({
                "date": normalize_workout_date(row[0]),
                "username": normalize_username(row[1] or actor),
                "activity": row[2] or "유산소",
                "durationSeconds": sheet_int(row[3], 0),
                "memo": row[4],
                "submissionId": row[5],
                "createdAt": row[6],
            })
        return parsed

    def append_cardio_log(self, cardio_log, username="", user_id=""):
        actor = self.sheet_actor(username, user_id)
        self.ensure_user_tabs(actor, user_id)
        worksheet = self.worksheet(self.CARDIO_LOGS_TAB, rows=500, cols=7)
        worksheet.append_row([
            cardio_log.get("date", ""),
            normalize_username(cardio_log.get("username") or actor),
            cardio_log.get("activity", "유산소"),
            as_int(cardio_log.get("durationSeconds"), 0),
            cardio_log.get("memo", ""),
            cardio_log.get("submissionId", ""),
            cardio_log.get("createdAt", ""),
        ], value_input_option="RAW", table_range="A1:G1")
        return True

    def load_replacements(self, username="", user_id=""):
        actor = self.sheet_actor(username, user_id)
        self.ensure_user_tabs(actor, user_id)
        worksheet = self.worksheet(self.REPLACEMENTS_TAB, rows=500, cols=15)
        rows = worksheet.get("A2:O") or []
        parsed = []
        for row in rows:
            row = [str(value).strip() for value in row] + [""] * 15
            if not row[0] or not row[4] or not row[5]:
                continue
            row_actor = row[14]
            item = {
                "date": row[0],
                "split": sheet_int(row[1]),
                "week": sheet_int(row[2], 1),
                "day": row[3],
                "originalExercise": row[4],
                "exercise": row[5],
                "setCount": sheet_int(row[6]),
                "bestWeight": sheet_float(row[7]),
                "bestReps": sheet_int(row[8]),
                "estimatedOneRm": sheet_float(row[9]),
                "volume": sheet_float(row[10]),
                "summary": row[11],
                "submissionId": row[12],
                "createdAt": row[13],
                "username": normalize_username("" if row_actor.startswith("user_") else row_actor) or normalize_username(username),
                "userId": row_actor if row_actor.startswith("user_") else "",
            }
            if normalize_username(item.get("username")) == self.sheet_actor(username, user_id):
                parsed.append(item)
        return parsed

    def append_replacements(self, replacements, username="", user_id=""):
        if not replacements:
            return True
        actor = self.sheet_actor(username, user_id)
        self.ensure_user_tabs(actor, user_id)
        worksheet = self.worksheet(self.REPLACEMENTS_TAB, rows=500, cols=15)
        rows = []
        for item in replacements:
            rows.append([
                item.get("date", ""),
                item.get("split", ""),
                item.get("week", ""),
                item.get("day", ""),
                item.get("originalExercise", ""),
                item.get("exercise", ""),
                item.get("setCount", ""),
                item.get("bestWeight", ""),
                item.get("bestReps", ""),
                item.get("estimatedOneRm", ""),
                item.get("volume", ""),
                item.get("summary", ""),
                item.get("submissionId", ""),
                item.get("createdAt", ""),
                normalize_username(item.get("username") or actor),
            ])
        worksheet.append_rows(rows, value_input_option="RAW", table_range="A1:O1")
        return True

    def load_submission_ids(self, username="", user_id=""):
        actor = self.sheet_actor(username, user_id)
        self.ensure_user_tabs(actor, user_id)
        worksheet = self.worksheet(self.SUBMISSIONS_TAB, rows=500, cols=8)
        rows = worksheet.get("A2:H") or []
        ids = {
            str(row[0]).strip()
            for row in rows
            if row and str(row[0]).strip() and len(row) > 1 and normalize_username(row[1]) == actor
        }
        return ids

    def append_submission(self, submission, username="", user_id=""):
        submission_id = str(submission.get("id") or "").strip()
        if not submission_id:
            return True
        actor = self.sheet_actor(username, user_id)
        self.ensure_user_tabs(actor, user_id)
        worksheet = self.worksheet(self.SUBMISSIONS_TAB, rows=500, cols=8)
        worksheet.append_row([
            submission_id,
            actor,
            submission.get("date", ""),
            submission.get("split", ""),
            submission.get("week", ""),
            submission.get("day", ""),
            submission.get("logCount", ""),
            submission.get("createdAt", ""),
        ], value_input_option="RAW", table_range="A1:H1")
        return True


def sheets_store():
    global _SHEETS_STORE
    if _SHEETS_STORE is None:
        _SHEETS_STORE = GoogleSheetsStore()
    return _SHEETS_STORE


def sheets_connected():
    return sheets_store().connected


def sheets_connected_cached():
    return bool(_SHEETS_STORE and _SHEETS_STORE.connected)


def state_cache_key(username=""):
    return safe_username_suffix(username) or "__shared__"


def cached_state(username="", allow_expired=False):
    if STATE_CACHE_SECONDS <= 0:
        return None
    cached = _STATE_CACHE.get(state_cache_key(username))
    if not cached:
        return None
    if not allow_expired and cached.get("expires_at", 0) <= time.time():
        return None
    return copy.deepcopy(cached.get("state"))


def set_state_cache(state, username=""):
    if STATE_CACHE_SECONDS <= 0:
        return
    _STATE_CACHE[state_cache_key(username)] = {
        "state": copy.deepcopy(state),
        "expires_at": time.time() + STATE_CACHE_SECONDS,
    }


def invalidate_state_cache(username=None):
    if username is None:
        _STATE_CACHE.clear()
        return
    _STATE_CACHE.pop(state_cache_key(username), None)


def load_auth_state():
    local_state = load_json(AUTH_FILE, {"users": [], "sessions": []})
    if not isinstance(local_state, dict):
        local_state = {"users": [], "sessions": []}

    store = sheets_store()
    if store.connected:
        try:
            state = {
                "users": store.load_users(),
                "sessions": store.load_sessions(),
            }
            save_json(AUTH_FILE, state)
            return state
        except Exception as exc:
            print(f"[warn] failed to load auth state from Google Sheets, using local file state: {exc}")

    return {
        "users": [normalize_user(user) for user in local_state.get("users", [])],
        "sessions": [normalize_session(session) for session in local_state.get("sessions", [])],
    }


def save_auth_state(users, sessions):
    users = [normalize_user(user) for user in users or [] if normalize_username(user.get("username"))]
    sessions = [normalize_session(session) for session in sessions or [] if session.get("tokenHash")]

    store = sheets_store()
    if store.connected:
        try:
            store.save_users(users)
            store.save_sessions(sessions)
        except Exception as exc:
            print(f"[warn] failed to save auth state to Google Sheets: {exc}")

    save_json(AUTH_FILE, {"users": users, "sessions": sessions})
    return users, sessions


def save_auth_local(users, sessions):
    users = [normalize_user(user) for user in users or [] if normalize_username(user.get("username"))]
    sessions = [normalize_session(session) for session in sessions or [] if session.get("tokenHash")]
    save_json(AUTH_FILE, {"users": users, "sessions": sessions})
    return users, sessions


def append_auth_user_and_session(auth_state, user, session):
    users = [normalize_user(item) for item in auth_state.get("users", [])]
    sessions = [normalize_session(item) for item in auth_state.get("sessions", []) if item.get("tokenHash")]
    user = normalize_user(user)
    session = normalize_session(session)

    store = sheets_store()
    if store.connected:
        store.append_session(session)
        store.append_user(user)

    users.append(user)
    sessions.append(session)
    return save_auth_local(users, sessions)


def append_auth_session(auth_state, session):
    users = [normalize_user(item) for item in auth_state.get("users", [])]
    sessions = [normalize_session(item) for item in auth_state.get("sessions", []) if item.get("tokenHash")]
    session = normalize_session(session)

    store = sheets_store()
    if store.connected:
        store.append_session(session)

    sessions.append(session)
    return save_auth_local(users, sessions)


def revoke_auth_session(auth_state, token_hash, revoked_at):
    users = [normalize_user(item) for item in auth_state.get("users", [])]
    sessions = [normalize_session(item) for item in auth_state.get("sessions", []) if item.get("tokenHash")]
    changed = False
    for session in sessions:
        if session.get("tokenHash") == token_hash and not session.get("revokedAt"):
            session["revokedAt"] = revoked_at
            changed = True

    store = sheets_store()
    if store.connected:
        changed = store.revoke_session(token_hash, revoked_at) or changed

    if changed:
        save_auth_local(users, sessions)
    return changed


def has_users(auth_state=None):
    state = auth_state or load_auth_state()
    return bool(active_users(state.get("users", [])))


def find_user_by_username(users, username):
    username = normalize_username(username)
    return next((user for user in users if user.get("username") == username and sheet_bool(user.get("active", True))), None)


def find_user_by_id(users, user_id):
    return next((user for user in users if user.get("id") == user_id and sheet_bool(user.get("active", True))), None)


def create_session_for_user(user):
    token = secrets.token_urlsafe(32)
    created_at = now_dt()
    session = {
        "tokenHash": session_token_hash(token),
        "userId": user.get("id"),
        "username": user.get("username"),
        "createdAt": created_at.isoformat(timespec="seconds"),
        "expiresAt": (created_at + timedelta(days=AUTH_SESSION_DAYS)).isoformat(timespec="seconds"),
        "revokedAt": "",
        "userAgent": request.headers.get("User-Agent", "")[:200],
    }
    _AUTH_SESSION_CACHE[session["tokenHash"]] = (time.time() + AUTH_CACHE_SECONDS, public_user(user))
    return token, session


def secure_cookie_request():
    return request.is_secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https"


def attach_session_cookie(response, token):
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=AUTH_SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=secure_cookie_request(),
        samesite="Lax",
        path="/",
    )
    return response


def clear_session_cookie(response):
    response.delete_cookie(AUTH_COOKIE_NAME, path="/", samesite="Lax")
    return response


def current_user_from_cookie(auth_state=None):
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        return None

    token_hash = session_token_hash(token)
    cached = _AUTH_SESSION_CACHE.get(token_hash)
    if cached and cached[0] > time.time():
        return cached[1]

    state = auth_state or load_auth_state()
    session = next((item for item in state.get("sessions", []) if item.get("tokenHash") == token_hash), None)
    if not session_is_active(session):
        _AUTH_SESSION_CACHE.pop(token_hash, None)
        return None

    user = find_user_by_id(state.get("users", []), session.get("userId"))
    if not user:
        _AUTH_SESSION_CACHE.pop(token_hash, None)
        return None

    safe_user = public_user(user)
    _AUTH_SESSION_CACHE[token_hash] = (time.time() + AUTH_CACHE_SECONDS, safe_user)
    return safe_user


PUBLIC_AUTH_PATHS = {
    "/api/auth/status",
    "/api/auth/register",
    "/api/auth/login",
    "/api/auth/logout",
}


@app.before_request
def require_auth_for_api():
    if request.method == "OPTIONS":
        return None
    if not request.path.startswith("/api/") or request.path in PUBLIC_AUTH_PATHS:
        return None

    user = current_user_from_cookie()
    if user:
        g.current_user = user
        return None

    return jsonify({
        "error": "unauthorized",
        "setupRequired": not has_users(),
    }), 401


def append_workout_logs_to_sheet(logs, username="", user_id=""):
    store = sheets_store()
    if not store.connected:
        return False
    try:
        return store.append_logs(logs, username, user_id)
    except Exception as exc:
        print(f"[warn] failed to append workout logs to Google Sheets: {exc}")
        try:
            if workout_logs_already_saved({"logs": store.load_logs(username, user_id)}, logs):
                print("[warn] workout logs append response failed, but rows are already present in Google Sheets")
                return True
        except Exception as verify_exc:
            print(f"[warn] failed to verify workout logs after append error: {verify_exc}")
    return False


def append_workout_replacements_to_sheet(replacements, username="", user_id=""):
    store = sheets_store()
    if not store.connected:
        return False
    try:
        return store.append_replacements(replacements, username, user_id)
    except Exception as exc:
        print(f"[warn] failed to append workout replacements to Google Sheets: {exc}")
        return False


def append_workout_submission_to_sheet(submission, username="", user_id=""):
    store = sheets_store()
    if not store.connected:
        return False
    try:
        return store.append_submission(submission, username, user_id)
    except Exception as exc:
        print(f"[warn] failed to append workout submission marker to Google Sheets: {exc}")
        return False


def append_cardio_log_to_sheet(cardio_log, username="", user_id=""):
    store = sheets_store()
    if not store.connected:
        return False
    try:
        return store.append_cardio_log(cardio_log, username, user_id)
    except Exception as exc:
        print(f"[warn] failed to append cardio log to Google Sheets: {exc}")
        try:
            if cardio_log_already_saved({"cardioLogs": store.load_cardio_logs(username, user_id)}, cardio_log):
                print("[warn] cardio append response failed, but row is already present in Google Sheets")
                return True
        except Exception as verify_exc:
            print(f"[warn] failed to verify cardio log after append error: {verify_exc}")
    return False


def replacement_key(item):
    return "|".join([
        str(item.get("username") or item.get("userId") or ""),
        str(item.get("submissionId") or ""),
        str(item.get("date") or ""),
        str(item.get("split") or ""),
        str(item.get("week") or ""),
        str(item.get("day") or ""),
        str(item.get("originalExercise") or ""),
        str(item.get("exercise") or ""),
    ])


def merge_replacements(*groups):
    merged = {}
    for group in groups:
        for item in group or []:
            normalized = normalize_replacement_item(item)
            if normalized:
                merged[replacement_key(normalized)] = normalized
    return list(merged.values())


def state_has_submission(state, submission_id):
    if not submission_id:
        return False
    for item in state.get("submissions", []):
        if isinstance(item, dict) and str(item.get("id") or "").strip() == submission_id:
            return True
        if str(item or "").strip() == submission_id:
            return True
    for log in state.get("logs", []):
        if str(log.get("submissionId") or "").strip() == submission_id:
            return True
    return False


def log_duplicate_key(log):
    return (
        str(log.get("date") or ""),
        as_int(log.get("split")),
        as_int(log.get("week"), 1),
        str(log.get("day") or ""),
        str(log.get("exercise") or ""),
        as_int(log.get("setNo")),
        round(as_float(log.get("weight")), 3),
        as_int(log.get("reps")),
        round(as_float(log.get("rpe")), 3),
        str(log.get("status") or ""),
        round(as_float(log.get("targetWeight")), 3),
        as_int(log.get("targetReps")),
    )


def workout_logs_already_saved(state, logs):
    if not logs:
        return False

    new_counts = {}
    for log in logs:
        key = log_duplicate_key(log)
        new_counts[key] = new_counts.get(key, 0) + 1

    existing_counts = {}
    for log in state.get("logs", []):
        key = log_duplicate_key(log)
        existing_counts[key] = existing_counts.get(key, 0) + 1

    return all(existing_counts.get(key, 0) >= count for key, count in new_counts.items())


def normalize_cardio_log(raw, username="", user_id=""):
    source = raw if isinstance(raw, dict) else {}
    return {
        "date": normalize_workout_date(source.get("date")),
        "username": normalize_username(source.get("username") or username),
        "userId": str(source.get("userId") or user_id or "").strip(),
        "activity": str(source.get("activity") or "유산소").strip() or "유산소",
        "durationSeconds": max(0, as_int(source.get("durationSeconds"), 0)),
        "memo": str(source.get("memo") or "").strip(),
        "submissionId": str(source.get("submissionId") or "").strip(),
        "createdAt": str(source.get("createdAt") or now_iso()),
    }


def cardio_duplicate_key(cardio_log):
    return (
        str(cardio_log.get("date") or ""),
        normalize_username(cardio_log.get("username")),
        str(cardio_log.get("activity") or ""),
        as_int(cardio_log.get("durationSeconds"), 0),
        str(cardio_log.get("memo") or ""),
    )


def format_duration_seconds(seconds):
    total_seconds = max(0, as_int(seconds, 0))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    rest_seconds = total_seconds % 60
    if hours:
        return f"{hours}시간 {minutes}분 {rest_seconds}초"
    if minutes:
        return f"{minutes}분 {rest_seconds}초"
    return f"{rest_seconds}초"


def cardio_log_already_saved(state, cardio_log):
    submission_id = str(cardio_log.get("submissionId") or "").strip()
    username = normalize_username(cardio_log.get("username"))
    date = str(cardio_log.get("date") or "")
    duplicate_key = cardio_duplicate_key(cardio_log)
    for existing in state.get("cardioLogs", []):
        existing_submission_id = str(existing.get("submissionId") or "").strip()
        if submission_id and existing_submission_id == submission_id:
            if normalize_username(existing.get("username")) == username and str(existing.get("date") or "") == date:
                return True
            continue
        if not submission_id and cardio_duplicate_key(existing) == duplicate_key:
            return True
    return False


def current_request_user():
    user = getattr(g, "current_user", None)
    if isinstance(user, dict):
        return user
    return {}


def current_request_user_id():
    user = current_request_user()
    if isinstance(user, dict):
        return str(user.get("id") or "").strip()
    return ""


def current_request_username():
    user = current_request_user()
    if isinstance(user, dict):
        return normalize_username(user.get("username"))
    return ""


def item_matches_user(item, user_id="", username=""):
    username = normalize_username(username)
    user_id = str(user_id or "").strip()
    if not user_id and not username:
        return True
    item_username = normalize_username(item.get("username"))
    item_user_id = str(item.get("userId") or "").strip()
    if username and item_username:
        return item_username == username
    if user_id and item_user_id:
        return item_user_id == user_id
    return False


def state_for_user(state, user_id="", username=""):
    if not user_id and not username:
        return state
    scoped = copy.deepcopy(state)
    scoped["logs"] = [log for log in state.get("logs", []) if item_matches_user(log, user_id, username)]
    scoped["replacements"] = [item for item in state.get("replacements", []) if item_matches_user(item, user_id, username)]
    scoped["cardioLogs"] = [item for item in state.get("cardioLogs", []) if item_matches_user(item, user_id, username)]
    return scoped


def sheet_has_submission(submission_id, username="", user_id=""):
    if not submission_id:
        return False
    store = sheets_store()
    if not store.connected:
        return False
    try:
        if submission_id in store.load_submission_ids(username, user_id):
            return True
    except Exception as exc:
        print(f"[warn] failed to load workout submission markers: {exc}")
    return False


def make_submission_record(submission_id, date, split, week, day_id, log_count):
    return {
        "id": str(submission_id or "").strip(),
        "date": date,
        "split": split,
        "week": week,
        "day": day_id,
        "logCount": log_count,
        "createdAt": now_iso(),
    }


def remember_submission(state, submission):
    submission_id = str(submission.get("id") or "").strip()
    if not submission_id or state_has_submission(state, submission_id):
        return
    state.setdefault("submissions", []).append(submission)
    state["submissions"] = state["submissions"][-250:]


def today_iso():
    try:
        tz = ZoneInfo(APP_TIMEZONE)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date().isoformat()


def normalize_workout_date(value):
    raw = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return today_iso()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return today_iso()


def load_legacy_gyms():
    legacy = load_json(GYM_SETTINGS_FILE, {})
    gyms = legacy.get("gyms") if isinstance(legacy, dict) else None
    if isinstance(gyms, list) and gyms:
        return legacy.get("activeGymId") or gyms[0].get("id"), gyms
    return DEFAULT_GYM["id"], [copy.deepcopy(DEFAULT_GYM)]


def state_file_for_username(username=""):
    suffix = safe_username_suffix(username)
    return STATE_DIR / f"app_state_{suffix}.json" if suffix else STATE_FILE


def load_file_state(username=""):
    state_path = state_file_for_username(username)
    state = load_json(state_path, None)
    if not isinstance(state, dict) and normalize_username(username):
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
    state.setdefault("cardioLogs", [])
    state.setdefault("replacements", [])
    state.setdefault("submissions", [])
    state.setdefault("gyms", [copy.deepcopy(DEFAULT_GYM)])
    state.setdefault("activeGymId", state["gyms"][0]["id"] if state["gyms"] else DEFAULT_GYM["id"])

    for key, value in DEFAULT_ONE_RMS.items():
        state["oneRms"].setdefault(key, value)

    if not state["gyms"]:
        state["gyms"].append(copy.deepcopy(DEFAULT_GYM))
        state["activeGymId"] = DEFAULT_GYM["id"]

    state["activeGymId"], state["gyms"] = normalize_gym_state(state.get("activeGymId"), state.get("gyms"))
    return state


def load_state(force_refresh=False, username="", user_id=""):
    username = normalize_username(username)
    stale_state = None
    if not force_refresh:
        state = cached_state(username)
        if state is not None:
            return state
        stale_state = cached_state(username, allow_expired=True)

    state = load_file_state(username)
    store = sheets_store()
    loaded_sheet_state = False
    logs_load_failed = False
    if store.connected:
        try:
            state["oneRms"].update(store.load_one_rms(username, user_id))
        except Exception as exc:
            print(f"[warn] failed to load 1RM from Google Sheets, using local file state: {exc}")
        try:
            state["logs"] = store.load_logs(username, user_id)
            loaded_sheet_state = True
        except Exception as exc:
            logs_load_failed = True
            print(f"[warn] failed to load workout logs from Google Sheets, using cached/local state: {exc}")
            if stale_state and stale_state.get("logs"):
                state["logs"] = stale_state.get("logs", [])
        try:
            state["cardioLogs"] = store.load_cardio_logs(username, user_id)
        except Exception as exc:
            print(f"[warn] failed to load cardio logs from Google Sheets, using cached/local state: {exc}")
            if stale_state and stale_state.get("cardioLogs"):
                state["cardioLogs"] = stale_state.get("cardioLogs", [])
        try:
            state["replacements"] = merge_replacements(state.get("replacements", []), store.load_replacements(username, user_id))
        except Exception as exc:
            print(f"[warn] failed to load replacement history from Google Sheets, using local file state: {exc}")
        try:
            state["submissions"] = list(store.load_submission_ids(username, user_id))
        except Exception as exc:
            print(f"[warn] failed to load workout submission markers from Google Sheets, using local file state: {exc}")
        try:
            active_gym_id, gyms = store.load_gyms(username, user_id)
            if gyms:
                state["activeGymId"], state["gyms"] = active_gym_id, gyms
            else:
                state["activeGymId"], state["gyms"] = normalize_gym_state(DEFAULT_GYM["id"], [copy.deepcopy(DEFAULT_GYM)])
                store.save_gyms(state.get("activeGymId"), state.get("gyms", []), username, user_id)
        except Exception as exc:
            print(f"[warn] failed to load gym settings from Google Sheets, using local file state: {exc}")
    state = state_for_user(state, user_id, username)
    if loaded_sheet_state:
        save_json(state_file_for_username(username), state)
    if not (logs_load_failed and not state.get("logs")):
        set_state_cache(state, username)
    return state


def save_state(state, sync_one_rms=True, sync_gyms=True, username="", user_id="") -> None:
    username = normalize_username(username)
    state["activeGymId"], state["gyms"] = normalize_gym_state(state.get("activeGymId"), state.get("gyms"))
    store = sheets_store()
    if store.connected:
        if sync_one_rms:
            try:
                store.save_one_rms(state.get("oneRms", {}), username, user_id)
            except Exception as exc:
                print(f"[warn] failed to save 1RM to Google Sheets: {exc}")
        if sync_gyms:
            try:
                store.save_gyms(state.get("activeGymId"), state.get("gyms", []), username, user_id)
            except Exception as exc:
                print(f"[warn] failed to save gym settings to Google Sheets: {exc}")
    save_json(state_file_for_username(username), state)
    set_state_cache(state, username)


def load_gym_state(username="", user_id=""):
    username = normalize_username(username)
    state = load_file_state(username)
    store = sheets_store()
    if store.connected:
        try:
            active_gym_id, gyms = store.load_gyms(username, user_id)
            if gyms:
                state["activeGymId"], state["gyms"] = active_gym_id, gyms
        except Exception as exc:
            print(f"[warn] failed to load gym settings from Google Sheets, using local file state: {exc}")
    state["activeGymId"], state["gyms"] = normalize_gym_state(state.get("activeGymId"), state.get("gyms"))
    return state


def save_gym_state(state, username="", user_id="") -> None:
    username = normalize_username(username)
    state["activeGymId"], state["gyms"] = normalize_gym_state(state.get("activeGymId"), state.get("gyms"))
    store = sheets_store()
    if store.connected:
        try:
            store.save_gyms(state.get("activeGymId"), state.get("gyms", []), username, user_id)
        except Exception as exc:
            print(f"[warn] failed to save gym settings to Google Sheets: {exc}")
    save_json(state_file_for_username(username), state)
    invalidate_state_cache(username)


def load_routines():
    global _ROUTINES_CACHE
    if _ROUTINES_CACHE is not None:
        return copy.deepcopy(_ROUTINES_CACHE)

    routines = load_json(ROUTINES_FILE, {})
    if not isinstance(routines, dict):
        routines = {}
    _ROUTINES_CACHE = routines
    return copy.deepcopy(_ROUTINES_CACHE)


def load_two_day_versions():
    global _TWO_DAY_VERSIONS_CACHE
    if _TWO_DAY_VERSIONS_CACHE is not None:
        return copy.deepcopy(_TWO_DAY_VERSIONS_CACHE)

    versions = load_json(TWO_DAY_VERSIONS_FILE, {})
    if not isinstance(versions, dict):
        versions = {}
    _TWO_DAY_VERSIONS_CACHE = versions
    return copy.deepcopy(_TWO_DAY_VERSIONS_CACHE)


def load_exercise_definitions():
    global _EXERCISE_DEFINITIONS_CACHE
    if _EXERCISE_DEFINITIONS_CACHE is not None:
        return _EXERCISE_DEFINITIONS_CACHE

    definitions = load_json(EXERCISE_DEFINITIONS_FILE, {})
    _EXERCISE_DEFINITIONS_CACHE = {
        "large": set(definitions.get("large_muscles") or []),
        "small": set(definitions.get("small_muscles") or []),
        "muscleGroups": {
            str(name).strip(): str(muscle).strip()
            for name, muscle in (definitions.get("muscle_groups") or {}).items()
            if str(name).strip() and str(muscle).strip()
        },
    }
    return _EXERCISE_DEFINITIONS_CACHE


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


ROUTINE_SPLITS = ("2", "3", "4", "5")
DEFAULT_ROUTINE_PROGRESS_ENTRY = {
    "version": "",
    "blockLength": 12,
    "baselineLogCount": 0,
    "startedAt": "",
}


def routine_progress_key(username="", user_id=""):
    username = normalize_username(username)
    return username or str(user_id or "").strip() or "_default"


def normalize_split_key(split):
    split_key = str(as_int(split, 0))
    return split_key if split_key in ROUTINE_SPLITS else "5"


def default_routine_progress_entry(split):
    split = normalize_split_key(split)
    entry = copy.deepcopy(DEFAULT_ROUTINE_PROGRESS_ENTRY)
    if split == "2":
        versions = load_two_day_versions()
        names = [name for name in ["ver.1", "ver.2"] if name in versions] or list(versions.keys())
        entry["version"] = names[0] if names else "ver.1"
    return entry


def normalize_routine_progress_entry(entry, split):
    split = normalize_split_key(split)
    normalized = default_routine_progress_entry(split)
    if isinstance(entry, dict):
        normalized.update(entry)

    if split == "2":
        versions = load_two_day_versions()
        names = [name for name in ["ver.1", "ver.2"] if name in versions] or list(versions.keys())
        if normalized.get("version") not in names:
            normalized["version"] = names[0] if names else "ver.1"
        if normalized.get("version") == "ver.1" and "ver.2" in names:
            normalized["nextVersion"] = "ver.2"
        elif normalized.get("version") == "ver.2" and "ver.1" in names:
            normalized["nextVersion"] = "ver.1"
        else:
            normalized["nextVersion"] = names[0] if names else normalized["version"]
    else:
        normalized["version"] = str(normalized.get("version") or "").strip()
        normalized["nextVersion"] = ""

    normalized["blockLength"] = max(1, as_int(normalized.get("blockLength"), DEFAULT_ROUTINE_PROGRESS_ENTRY["blockLength"]))
    normalized["baselineLogCount"] = max(0, as_int(normalized.get("baselineLogCount"), 0))
    normalized["startedAt"] = str(normalized.get("startedAt") or "").strip()
    return normalized


def normalize_routine_progress(progress):
    normalized = {}
    if not isinstance(progress, dict):
        progress = {}
    for split in ROUTINE_SPLITS:
        normalized[split] = normalize_routine_progress_entry(progress.get(split), split)
    return normalized


def load_routine_progress(username="", user_id=""):
    username = normalize_username(username)
    all_settings = load_json(ROUTINE_PROGRESS_FILE, {})
    if not isinstance(all_settings, dict):
        all_settings = {}
    key = routine_progress_key(username, user_id)
    progress = all_settings.get(key, {})
    store = sheets_store()
    if store.connected and username:
        try:
            sheet_progress = store.load_routine_progress(username, user_id)
            if sheet_progress:
                progress = {**progress, **sheet_progress} if isinstance(progress, dict) else sheet_progress
        except Exception as exc:
            print(f"[warn] failed to load routine progress from Google Sheets: {exc}")
    return normalize_routine_progress(progress)


def save_routine_progress(progress, username="", user_id=""):
    username = normalize_username(username)
    all_settings = load_json(ROUTINE_PROGRESS_FILE, {})
    if not isinstance(all_settings, dict):
        all_settings = {}
    key = routine_progress_key(username, user_id)
    all_settings[key] = normalize_routine_progress(progress)
    store = sheets_store()
    if store.connected and username:
        try:
            store.save_routine_progress(all_settings[key], username, user_id)
        except Exception as exc:
            print(f"[warn] failed to save routine progress to Google Sheets: {exc}")
    save_json(ROUTINE_PROGRESS_FILE, all_settings)
    return all_settings[key]


def active_routine_progress(progress, split):
    progress = normalize_routine_progress(progress)
    return progress[normalize_split_key(split)]


def routines_for_progress(progress=None):
    routines = load_routines()
    versions = load_two_day_versions()
    if versions:
        selected_progress = active_routine_progress(progress, 2)
        active = selected_progress.get("version")
        selected = versions.get(active) or next(iter(versions.values()))
        routines["2"] = copy.deepcopy(selected)
    return routines


def split_log_count(state, split):
    split = as_int(split, 0)
    return sum(1 for log in state.get("logs", []) if as_int(log.get("split")) == split)


def split_logs_since_baseline(state, split, baseline):
    split = as_int(split, 0)
    split_logs = [log for log in state.get("logs", []) if as_int(log.get("split")) == split]
    baseline = min(max(0, as_int(baseline, 0)), len(split_logs))
    return split_logs[baseline:], baseline


def workout_sessions_from_logs(logs):
    sessions = []
    last_key = None
    for log in logs:
        key = str(log.get("submissionId") or "").strip()
        if not key:
            key = "|".join([
                str(log.get("date") or ""),
                str(log.get("split") or ""),
                str(log.get("week") or ""),
                str(log.get("day") or ""),
            ])
        if key == last_key:
            continue
        sessions.append(log)
        last_key = key
    return sessions


def routine_position_for_split(state, split, entry, routine_day_count):
    routine_day_count = max(1, as_int(routine_day_count, 1))
    tracked_logs, baseline = split_logs_since_baseline(state, split, entry.get("baselineLogCount"))
    sessions = workout_sessions_from_logs(tracked_logs)
    next_session = len(sessions) + 1
    active_week = ((next_session - 1) // routine_day_count) + 1
    program_day = ((next_session - 1) % routine_day_count) + 1
    next_recommended = "Day 1"
    last_completed = None
    if sessions:
        last_day = day_number(sessions[-1].get("day"))
        last_completed = f"Day {last_day}"
        next_num = last_day + 1 if last_day < routine_day_count else 1
        next_recommended = f"Day {next_num}"
    return {
        "baseline": baseline,
        "week": active_week,
        "programDay": program_day,
        "completedSessions": len(sessions),
        "lastCompletedDay": last_completed,
        "nextRecommendedDay": next_recommended,
    }


def routine_progress_payload(state, username="", user_id="", progress=None, routines=None):
    progress = normalize_routine_progress(progress or load_routine_progress(username, user_id))
    routines = routines or routines_for_progress(progress)
    payload = {}
    for split in ROUTINE_SPLITS:
        entry = normalize_routine_progress_entry(progress.get(split), split)
        routine_day_count = len(routines.get(split, [])) or as_int(split, 1)
        position = routine_position_for_split(state, split, entry, routine_day_count)

        block_length = max(1, as_int(entry.get("blockLength"), 12))
        payload[split] = {
            "split": as_int(split),
            "version": entry.get("version", ""),
            "nextVersion": entry.get("nextVersion", ""),
            "blockLength": block_length,
            "baselineLogCount": position["baseline"],
            "startedAt": entry.get("startedAt", ""),
            "week": position["week"],
            "programDay": position["programDay"],
            "completedSessions": position["completedSessions"],
            "phase": "rest" if position["week"] > block_length else "training",
            "lastCompletedDay": position["lastCompletedDay"],
            "nextRecommendedDay": position["nextRecommendedDay"],
            "routineDayCount": routine_day_count,
        }
    return payload


def two_day_program_payload(state, username="", user_id="", progress=None, routines=None):
    return routine_progress_payload(state, username, user_id, progress, routines)["2"]


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


def clamp_target_reps(value, min_reps, max_reps):
    if max_reps < min_reps:
        max_reps = min_reps
    target = as_int(value, min_reps)
    return min(max(target, min_reps), max_reps)


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
    if lift_type in {"squat", "bench", "deadlift"}:
        return as_float(one_rms.get(lift_type), DEFAULT_ONE_RMS[lift_type])
    return 100.0


def latest_exercise_logs(logs, split, exercise_name):
    matching = [log for log in logs if log.get("split") == split and log.get("exercise") == exercise_name and log.get("date")]
    if not matching:
        return []
    latest_date = max(log["date"] for log in matching)
    return [log for log in matching if log.get("date") == latest_date]


def log_checked(log):
    if "completed" in log:
        return sheet_bool(log.get("completed"))
    if "checked" in log:
        return sheet_bool(log.get("checked"))
    return str(log.get("status", "")).upper() == "SUCCESS"


def set_succeeded(log, rpe_target=None):
    target_rpe = as_float(rpe_target if rpe_target is not None else log.get("targetRpe"), 8.0)
    rpe = as_float(log.get("rpe"))
    rpe_ok = rpe > 0 and rpe <= target_rpe
    return (
        log_checked(log)
        and as_float(log.get("weight")) > 0
        and as_float(log.get("weight")) + 0.001 >= as_float(log.get("targetWeight"))
        and as_int(log.get("reps")) > 0
        and as_int(log.get("reps")) >= as_int(log.get("targetReps"))
        and rpe_ok
    )


def routine_exercise_lookup(routines, split):
    lookup = {}
    for day in routines.get(str(split), []):
        for ex in day.get("exercises", []):
            lookup[ex.get("name")] = ex
    for days in routines.values():
        for day in days:
            for ex in day.get("exercises", []):
                lookup.setdefault(ex.get("name"), ex)
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
                    prev_target_weight = as_float(prev_last.get("targetWeight"), prev_weight)
                    prev_target_reps = clamp_target_reps(prev_last.get("targetReps"), min_reps, max_reps)

                    if all(set_succeeded(log, rpe_target) for log in previous_sorted):
                        if prev_target_reps < max_reps:
                            target_weight = prev_weight
                            target_reps = prev_target_reps + 1
                        else:
                            target_weight = prev_weight + get_increment(name)
                            target_reps = min_reps
                    else:
                        target_weight = prev_target_weight
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


def workout_status_payload(state, routines=None, progress=None):
    active_split = as_int(state["oneRms"].get("activeSplit"), 5)
    routines = routines or load_routines()
    routine_days = routines.get(str(active_split), [])
    routine_day_count = len(routine_days) or active_split
    progress = normalize_routine_progress(progress or {})
    active_progress = active_routine_progress(progress, active_split)
    position = routine_position_for_split(state, active_split, active_progress, routine_day_count)

    return {
        "sheetsConnected": sheets_connected(),
        "routineDayCount": routine_day_count,
        "week": position["week"],
        "programDay": position["programDay"],
        "completedSessions": position["completedSessions"],
        "lastCompletedDay": position["lastCompletedDay"],
        "nextRecommendedDay": position["nextRecommendedDay"],
    }


def target_muscle(exercise_name):
    raw_name = (exercise_name or "").strip()
    definitions = load_exercise_definitions()
    explicit = definitions["muscleGroups"].get(raw_name)
    if explicit:
        return explicit

    name = raw_name.lower()
    if any(token in name for token in ["벤치프레스", "bench", "체스트", "chest", "플라이", "fly", "크로스오버", "딥스", "dips"]):
        return "가슴"
    if any(token in name for token in ["로우", "row", "풀다운", "pulldown", "풀업", "pull-up", "pull up", "랫 풀", "암 풀"]):
        return "등"
    if any(token in name for token in ["스쿼트", "squat", "데드리프트", "deadlift", "루마니안", "런지", "레그", "leg", "카프", "calf"]):
        return "하체"
    if any(token in name for token in ["오버헤드 프레스", "ohp", "숄더", "shoulder", "레터럴", "lateral", "페이스 풀", "face pull"]):
        return "어깨"
    if any(token in name for token in ["컬", "curl", "트라이셉스", "triceps", "푸시다운", "푸쉬다운", "pushdown"]):
        return "팔"
    return "기타"


def normalize_logs(raw_logs, split, week, day_id, exercise_defs=None, submission_id="", username="", user_id=""):
    today = today_iso()
    normalized = []
    exercise_defs = exercise_defs or {}
    username = normalize_username(username)
    for raw in raw_logs or []:
        log = dict(raw)
        log["date"] = log.get("date") or today
        log["submissionId"] = str(log.get("submissionId") or submission_id or "").strip()
        log["username"] = normalize_username(log.get("username") or username)
        log["userId"] = str(log.get("userId") or user_id or "").strip()
        log["split"] = split
        log["week"] = week
        log["day"] = day_id
        log["setNo"] = as_int(log.get("setNo"), 1)
        log["targetWeight"] = as_float(log.get("targetWeight"))
        log["weight"] = as_float(log.get("weight"))
        log["targetReps"] = as_int(log.get("targetReps"))
        log["reps"] = as_int(log.get("reps"))
        log["rpe"] = as_float(log.get("rpe"))
        ex_def = exercise_defs.get(log.get("exercise"), {})
        log["targetRpe"] = as_float(log.get("targetRpe"), as_float(ex_def.get("rpeTarget"), 8.0))
        if log_checked(log) and log["rpe"] <= 0:
            log["rpe"] = log["targetRpe"]
        log["completed"] = log_checked(log)
        log["checked"] = log_checked(log)
        log["status"] = "SUCCESS" if set_succeeded(log, log["targetRpe"]) else "FAIL"
        normalized.append(log)
    return normalized


def normalize_replacement_item(raw):
    source = raw if isinstance(raw, dict) else {}
    original = str(source.get("originalExercise") or "").strip()
    exercise = str(source.get("exercise") or "").strip()
    if not original or not exercise or original == exercise:
        return None
    best_weight = as_float(source.get("bestWeight"))
    best_reps = as_int(source.get("bestReps"))
    estimated = as_float(source.get("estimatedOneRm"))
    if not estimated and best_weight > 0 and best_reps > 0:
        estimated = best_weight * (1 + best_reps / 30)
    return {
        "date": str(source.get("date") or today_iso()),
        "split": as_int(source.get("split")),
        "week": as_int(source.get("week"), 1),
        "day": str(source.get("day") or ""),
        "originalExercise": original,
        "exercise": exercise,
        "setCount": as_int(source.get("setCount")),
        "bestWeight": best_weight,
        "bestReps": best_reps,
        "estimatedOneRm": round(estimated, 2) if estimated else 0.0,
        "volume": as_float(source.get("volume")),
        "summary": str(source.get("summary") or "").strip(),
        "submissionId": str(source.get("submissionId") or "").strip(),
        "createdAt": str(source.get("createdAt") or now_iso()),
        "username": normalize_username(source.get("username")),
        "userId": str(source.get("userId") or "").strip(),
    }


def normalize_replacements(raw_replacements, split, week, day_id, date, submission_id, username="", user_id=""):
    normalized = []
    username = normalize_username(username)
    for raw in raw_replacements or []:
        item = normalize_replacement_item({
            **(raw if isinstance(raw, dict) else {}),
            "date": date,
            "split": split,
            "week": week,
            "day": day_id,
            "submissionId": submission_id,
            "username": username,
            "userId": user_id,
        })
        if item:
            normalized.append(item)
    return normalized


def duplicate_finish_response(logs):
    return {
        "status": "SUCCESS",
        "feedback": "이미 저장된 운동입니다. 중복 저장 없이 처리했습니다.",
        "sheetsConnected": sheets_connected(),
        "totalVolume": sum(log["weight"] * log["reps"] for log in logs if log["status"] == "SUCCESS"),
        "completedSets": sum(1 for log in logs if log["status"] == "SUCCESS"),
        "totalSets": len(logs),
        "progressReport": ["중복 제출이라 같은 운동을 다시 저장하지 않았습니다."],
        "weeklyMuscleSets": {"가슴": 0, "등": 0, "하체": 0, "어깨": 0, "팔": 0},
        "duplicate": True,
    }


def free_workout_feedback(logs):
    weekly_muscle_sets = {"가슴": 0, "등": 0, "하체": 0, "어깨": 0, "팔": 0}
    for log in logs:
        if log.get("status") != "SUCCESS":
            continue
        muscle = target_muscle(log.get("exercise"))
        if muscle in weekly_muscle_sets:
            weekly_muscle_sets[muscle] += 1

    completed_sets = sum(1 for log in logs if log["status"] == "SUCCESS")
    return {
        "status": "SUCCESS" if completed_sets else "FAIL",
        "feedback": "자유운동 기록을 저장했습니다.",
        "sheetsConnected": sheets_connected(),
        "totalVolume": sum(log["weight"] * log["reps"] for log in logs if log["status"] == "SUCCESS"),
        "completedSets": completed_sets,
        "totalSets": len(logs),
        "progressReport": ["자유운동은 루틴 진행도와 과부하 목표를 변경하지 않습니다."],
        "weeklyMuscleSets": weekly_muscle_sets,
    }


def day_number(day_id):
    match = re.search(r"\d+", day_id or "")
    return int(match.group(0)) if match else 1


def evaluate_and_update(state, logs, split, week, day_id, routines=None):
    routines = routines or load_routines()
    exercise_defs = routine_exercise_lookup(routines, split)

    logs_by_exercise = {}
    for log in logs:
        logs_by_exercise.setdefault(log.get("exercise"), []).append(log)

    progress_report = []
    all_sets_success = True
    has_failure = False
    total_rpe = 0.0
    rpe_count = 0

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

        prev_target_reps = clamp_target_reps(
            ex_logs[-1].get("targetReps"),
            min_reps,
            max_reps,
        )
        if ex_all_success:
            if prev_target_reps < max_reps:
                progress_report.append(f"🔼 {exercise_name}: 다음 목표 {prev_target_reps + 1}회")
            else:
                progress_report.append(f"⚡ {exercise_name}: 다음 목표 +{get_increment(exercise_name)}kg, {min_reps}회")
        else:
            progress_report.append(f"❄️ {exercise_name}: 유지")

    avg_rpe = total_rpe / rpe_count if rpe_count else 0.0

    if has_failure:
        status = "FAIL"
        feedback = f"⚠️ 목표를 채우지 못한 세트가 있습니다. 평균 RPE는 {avg_rpe:.1f}이고, 다음에는 같은 목표로 재도전합니다."
    else:
        status = "SUCCESS"
        if all_sets_success:
            feedback = "🎉 목표와 RPE 기준을 만족했습니다. 다음 목표로 진행합니다."
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
        "sheetsConnected": sheets_connected(),
        "totalVolume": sum(log["weight"] * log["reps"] for log in logs if log["status"] == "SUCCESS"),
        "completedSets": sum(1 for log in logs if log["status"] == "SUCCESS"),
        "totalSets": len(logs),
        "progressReport": progress_report,
        "weeklyMuscleSets": weekly_muscle_sets,
    }


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/healthz")
def healthz():
    return jsonify({
        "ok": True,
        "release": APP_RELEASE,
        "commit": APP_BUILD_COMMIT,
    })


@app.route("/api/auth/status")
def auth_status():
    user = current_user_from_cookie()
    if user:
        return jsonify({
            "authenticated": True,
            "user": user,
            "setupRequired": False,
            "sheetsConnected": sheets_connected_cached(),
        })

    auth_state = load_auth_state()
    user = current_user_from_cookie(auth_state)
    return jsonify({
        "authenticated": bool(user),
        "user": user,
        "setupRequired": not has_users(auth_state),
        "sheetsConnected": sheets_connected(),
    })


@app.route("/api/auth/register", methods=["POST"])
def auth_register():
    auth_state = load_auth_state()

    if has_users(auth_state):
        return jsonify({"error": "이미 계정이 있습니다. 로그인해주세요."}), 409

    body = request.get_json(silent=True) or {}
    username = normalize_username(body.get("username"))
    password = str(body.get("password") or "")
    display_name = str(body.get("displayName") or username).strip()

    if len(username) < 2:
        return jsonify({"error": "아이디는 2글자 이상으로 입력해주세요."}), 400
    if len(password) < 4:
        return jsonify({"error": "비밀번호는 4글자 이상으로 입력해주세요."}), 400

    salt, password_hash = hash_password(password)
    user = normalize_user({
        "id": f"user_{int(time.time() * 1000)}",
        "username": username,
        "displayName": display_name or username,
        "passwordSalt": salt,
        "passwordHash": password_hash,
        "iterations": AUTH_PASSWORD_ITERATIONS,
        "active": True,
        "createdAt": now_iso(),
        "lastLoginAt": now_iso(),
    })
    token, session = create_session_for_user(user)
    try:
        append_auth_user_and_session(auth_state, user, session)
    except Exception as exc:
        print(f"[warn] failed to create auth account: {exc}")
        return jsonify({"error": "계정 저장에 실패했습니다. 잠시 후 다시 시도해주세요."}), 503

    response = make_response(jsonify({
        "authenticated": True,
        "user": public_user(user),
        "setupRequired": False,
    }))
    return attach_session_cookie(response, token)


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    auth_state = load_auth_state()
    users = auth_state.get("users", [])

    if not has_users(auth_state):
        return jsonify({"error": "먼저 계정을 만들어주세요.", "setupRequired": True}), 400

    body = request.get_json(silent=True) or {}
    username = normalize_username(body.get("username"))
    password = str(body.get("password") or "")
    user = find_user_by_username(users, username)

    if not user or not verify_password(password, user.get("passwordSalt"), user.get("passwordHash"), user.get("iterations")):
        return jsonify({"error": "아이디 또는 비밀번호가 맞지 않습니다."}), 401

    user["lastLoginAt"] = now_iso()
    token, session = create_session_for_user(user)
    try:
        append_auth_session(auth_state, session)
    except Exception as exc:
        print(f"[warn] failed to create auth session: {exc}")
        return jsonify({"error": "로그인 세션 저장에 실패했습니다. 잠시 후 다시 시도해주세요."}), 503

    response = make_response(jsonify({
        "authenticated": True,
        "user": public_user(user),
        "setupRequired": False,
    }))
    return attach_session_cookie(response, token)


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if token:
        token_hash = session_token_hash(token)
        auth_state = load_auth_state()
        try:
            revoke_auth_session(auth_state, token_hash, now_iso())
        except Exception as exc:
            print(f"[warn] failed to revoke auth session: {exc}")
        _AUTH_SESSION_CACHE.pop(token_hash, None)

    response = make_response(jsonify({"success": True, "authenticated": False}))
    return clear_session_cookie(response)


@app.route("/<path:path>")
def static_files(path):
    static_root = STATIC_DIR.resolve()
    target = (static_root / path).resolve()
    try:
        target.relative_to(static_root)
    except ValueError:
        return jsonify({"error": "not found"}), 404

    if target.is_file():
        return send_from_directory(STATIC_DIR, path)

    if path.startswith("api/"):
        return jsonify({"error": "not found"}), 404

    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/workout/settings", methods=["GET", "POST"])
def workout_settings():
    username = current_request_username()
    user_id = current_request_user_id()
    state = load_state(username=username, user_id=user_id)
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        for key, default in DEFAULT_ONE_RMS.items():
            if key in body:
                state["oneRms"][key] = bool(body[key]) if isinstance(default, bool) else as_float(body[key], default)
        state["oneRms"]["activeSplit"] = as_int(state["oneRms"].get("activeSplit"), 5)
        save_state(state, username=username, user_id=user_id)
        return jsonify(state["oneRms"])

    return jsonify({"oneRms": state["oneRms"], "sheetsConnected": sheets_connected()})


@app.route("/api/workout/bootstrap")
def workout_bootstrap():
    username = current_request_username()
    user_id = current_request_user_id()
    state = load_state(username=username, user_id=user_id)
    progress = load_routine_progress(username, user_id)
    routines = routines_for_progress(progress)
    progress_payload = routine_progress_payload(state, username, user_id, progress, routines)
    return jsonify({
        "oneRms": state["oneRms"],
        "sheetsConnected": sheets_connected(),
        "gyms": state.get("gyms", []),
        "activeGymId": state.get("activeGymId"),
        "exerciseDefinitions": load_json(EXERCISE_DEFINITIONS_FILE, {}),
        "routine": apply_progression(routines, state),
        "status": workout_status_payload(state, routines, progress),
        "routineProgress": progress_payload,
        "twoDayProgram": progress_payload["2"],
        "logs": state.get("logs", []),
        "replacements": state.get("replacements", []),
        "cardioLogs": state.get("cardioLogs", []),
    })


@app.route("/api/workout/routine")
def workout_routine():
    username = current_request_username()
    user_id = current_request_user_id()
    state = load_state(username=username, user_id=user_id)
    return jsonify(apply_progression(routines_for_progress(load_routine_progress(username, user_id)), state))


@app.route("/api/workout/status")
def workout_status():
    username = current_request_username()
    user_id = current_request_user_id()
    state = load_state(username=username, user_id=user_id)
    progress = load_routine_progress(username, user_id)
    routines = routines_for_progress(progress)
    progress_payload = routine_progress_payload(state, username, user_id, progress, routines)
    payload = workout_status_payload(state, routines, progress)
    payload["routineProgress"] = progress_payload
    payload["twoDayProgram"] = progress_payload["2"]
    return jsonify(payload)


@app.route("/api/routine-progress", methods=["GET", "POST"])
def routine_progress():
    username = current_request_username()
    user_id = current_request_user_id()
    state = load_state(username=username, user_id=user_id)
    progress = load_routine_progress(username, user_id)
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        split = normalize_split_key(body.get("split", state["oneRms"].get("activeSplit", 5)))
        current = normalize_routine_progress_entry(progress.get(split), split)
        if body.get("reset"):
            current["baselineLogCount"] = split_log_count(state, split)
            current["startedAt"] = today_iso()
        if split == "2" and "version" in body:
            next_version = str(body.get("version") or current.get("version"))
            if next_version != current.get("version"):
                current["baselineLogCount"] = split_log_count(state, split)
                current["startedAt"] = today_iso()
            current["version"] = next_version
        if "blockLength" in body:
            current["blockLength"] = as_int(body.get("blockLength"), current.get("blockLength", 12))
        progress[split] = normalize_routine_progress_entry(current, split)
        progress = save_routine_progress(progress, username, user_id)
    routines = routines_for_progress(progress)
    payload = routine_progress_payload(state, username, user_id, progress, routines)
    return jsonify({
        "progress": payload,
        "active": payload[normalize_split_key(state["oneRms"].get("activeSplit", 5))],
        "twoDayProgram": payload["2"],
    })


@app.route("/api/two-day-program", methods=["GET", "POST"])
def two_day_program():
    username = current_request_username()
    user_id = current_request_user_id()
    state = load_state(username=username, user_id=user_id)
    progress = load_routine_progress(username, user_id)
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        current = normalize_routine_progress_entry(progress.get("2"), 2)
        if "version" in body:
            next_version = str(body.get("version") or current.get("version"))
            if next_version != current.get("version"):
                current["baselineLogCount"] = split_log_count(state, 2)
                current["startedAt"] = today_iso()
            current["version"] = next_version
        if "blockLength" in body:
            current["blockLength"] = as_int(body.get("blockLength"), current.get("blockLength", 12))
        progress["2"] = normalize_routine_progress_entry(current, 2)
        progress = save_routine_progress(progress, username, user_id)
    routines = routines_for_progress(progress)
    return jsonify(two_day_program_payload(state, username, user_id, progress, routines))


@app.route("/api/workout/logs")
def workout_logs():
    return jsonify(load_state(username=current_request_username(), user_id=current_request_user_id()).get("logs", []))


@app.route("/api/cardio/logs")
def cardio_logs():
    return jsonify(load_state(username=current_request_username(), user_id=current_request_user_id()).get("cardioLogs", []))


@app.route("/api/workout/replacements")
def workout_replacements():
    return jsonify(load_state(username=current_request_username(), user_id=current_request_user_id()).get("replacements", []))


@app.route("/api/cardio/finish", methods=["POST"])
def cardio_finish():
    started_at = time.perf_counter()
    username = current_request_username()
    user_id = current_request_user_id()
    state = load_state(username=username, user_id=user_id)
    body = request.get_json(silent=True) or {}
    cardio_log = normalize_cardio_log({
        "date": body.get("date"),
        "username": username,
        "userId": user_id,
        "activity": body.get("activity") or "유산소",
        "durationSeconds": body.get("durationSeconds"),
        "memo": body.get("memo"),
        "submissionId": body.get("submissionId"),
    }, username, user_id)

    if cardio_log["durationSeconds"] <= 0:
        return jsonify({
            "error": "invalid_duration",
            "message": "유산소 시간이 1초 이상이어야 저장할 수 있습니다.",
            "retryable": False,
        }), 400

    if cardio_log_already_saved(state, cardio_log):
        return jsonify({
            "status": "SUCCESS",
            "feedback": "이미 저장된 유산소 기록입니다. 중복 저장 없이 처리했습니다.",
            "sheetsConnected": sheets_connected(),
            "totalVolume": 0,
            "completedSets": 1,
            "totalSets": 1,
            "progressReport": [f"유산소 {format_duration_seconds(cardio_log['durationSeconds'])}"],
            "weeklyMuscleSets": {"가슴": 0, "등": 0, "하체": 0, "어깨": 0, "팔": 0},
            "duplicate": True,
        })

    store = sheets_store()
    saved_to_sheet = False
    if REQUIRE_SHEETS_FOR_FINISH and not store.connected:
        return jsonify({
            "error": "sheet_unavailable",
            "message": "Google Sheets 연결이 끊겨 유산소 기록을 저장하지 못했습니다.",
            "retryable": True,
        }), 503

    if store.connected:
        saved_to_sheet = append_cardio_log_to_sheet(cardio_log, username, user_id)
        if not saved_to_sheet:
            return jsonify({
                "error": "sheet_save_failed",
                "message": "유산소 기록을 Google Sheets에 저장하지 못했습니다.",
                "retryable": True,
            }), 503

    state.setdefault("cardioLogs", []).append(cardio_log)
    save_state(state, sync_one_rms=False, sync_gyms=False, username=username, user_id=user_id)
    total_ms = int((time.perf_counter() - started_at) * 1000)
    print(
        f"[cardio] saved submission={cardio_log.get('submissionId') or '-'} "
        f"user={username or user_id or '-'} sheet={saved_to_sheet if store.connected else 'local'} total={total_ms}ms",
        flush=True,
    )
    return jsonify({
        "status": "SUCCESS",
        "feedback": "유산소 기록을 저장했습니다.",
        "sheetsConnected": saved_to_sheet if store.connected else sheets_connected(),
        "totalVolume": 0,
        "completedSets": 1,
        "totalSets": 1,
        "progressReport": [f"유산소 {format_duration_seconds(cardio_log['durationSeconds'])}"],
        "weeklyMuscleSets": {"가슴": 0, "등": 0, "하체": 0, "어깨": 0, "팔": 0},
        "submissionId": cardio_log.get("submissionId", ""),
    })


@app.route("/api/workout/finish", methods=["POST"])
def workout_finish():
    started_at = time.perf_counter()
    username = current_request_username()
    user_id = current_request_user_id()
    state = load_state(username=username, user_id=user_id)
    load_ms = int((time.perf_counter() - started_at) * 1000)
    body = request.get_json(silent=True) or {}
    split = as_int(body.get("split"), as_int(state["oneRms"].get("activeSplit"), 5))
    week = as_int(body.get("week"), 1)
    day_id = body.get("day") or "Day 1"
    submission_id = str(body.get("submissionId") or "").strip()
    date = normalize_workout_date(body.get("date"))
    active_routines = routines_for_progress(load_routine_progress(username, user_id))
    exercise_defs = routine_exercise_lookup(active_routines, split)
    logs = normalize_logs(body.get("logs", []), split, week, day_id, exercise_defs, submission_id, username, user_id)
    for log in logs:
        log["date"] = date
    replacements = normalize_replacements(body.get("replacements", []), split, week, day_id, date, submission_id, username, user_id)

    duplicate_check_started_at = time.perf_counter()
    is_duplicate = (
        bool(submission_id and (state_has_submission(state, submission_id) or sheet_has_submission(submission_id, username, user_id)))
        or workout_logs_already_saved(state, logs)
    )
    duplicate_check_ms = int((time.perf_counter() - duplicate_check_started_at) * 1000)
    if is_duplicate:
        known_keys = {replacement_key(item) for item in state.get("replacements", [])}
        missing_replacements = [item for item in replacements if replacement_key(item) not in known_keys]
        if missing_replacements:
            append_workout_replacements_to_sheet(missing_replacements, username, user_id)
            state["replacements"] = merge_replacements(state.get("replacements", []), missing_replacements)
        if submission_id and not state_has_submission(state, submission_id):
            submission = make_submission_record(submission_id, date, split, week, day_id, len(logs))
            remember_submission(state, submission)
            append_workout_submission_to_sheet(submission, username, user_id)
        if missing_replacements or submission_id:
            save_state(state, sync_one_rms=False, sync_gyms=False, username=username, user_id=user_id)
        print(
            f"[finish] duplicate submission={submission_id or '-'} logs={len(logs)} "
            f"load={load_ms}ms duplicate_check={duplicate_check_ms}ms "
            f"total={int((time.perf_counter() - started_at) * 1000)}ms",
            flush=True,
        )
        return jsonify(duplicate_finish_response(logs))

    store = sheets_store()
    logs_saved_to_sheet = False
    replacements_saved_to_sheet = False
    logs_sheet_ms = 0
    replacements_sheet_ms = 0
    if REQUIRE_SHEETS_FOR_FINISH and not store.connected:
        return jsonify({
            "error": "sheet_unavailable",
            "message": "Google Sheets 연결이 끊겨 운동 기록을 저장하지 못했습니다.",
            "retryable": True,
        }), 503

    if store.connected:
        sheet_started_at = time.perf_counter()
        logs_saved_to_sheet = append_workout_logs_to_sheet(logs, username, user_id)
        logs_sheet_ms = int((time.perf_counter() - sheet_started_at) * 1000)
        if not logs_saved_to_sheet:
            print(
                f"[finish] sheet_save_failed submission={submission_id or '-'} logs={len(logs)} "
                f"load={load_ms}ms duplicate_check={duplicate_check_ms}ms "
                f"logs_sheet={logs_sheet_ms}ms total={int((time.perf_counter() - started_at) * 1000)}ms",
                flush=True,
            )
            return jsonify({
                "error": "sheet_save_failed",
                "message": "운동 기록을 Google Sheets에 저장하지 못했습니다.",
                "retryable": True,
            }), 503
        replacements_started_at = time.perf_counter()
        replacements_saved_to_sheet = append_workout_replacements_to_sheet(replacements, username, user_id)
        replacements_sheet_ms = int((time.perf_counter() - replacements_started_at) * 1000)

    feedback = free_workout_feedback(logs) if split == 0 else evaluate_and_update(copy.deepcopy(state), logs, split, week, day_id, active_routines)
    state["logs"].extend(logs)
    state["replacements"] = merge_replacements(state.get("replacements", []), replacements)
    submission_sheet_ms = 0
    if submission_id:
        submission = make_submission_record(submission_id, date, split, week, day_id, len(logs))
        remember_submission(state, submission)
        submission_started_at = time.perf_counter()
        append_workout_submission_to_sheet(submission, username, user_id)
        submission_sheet_ms = int((time.perf_counter() - submission_started_at) * 1000)
    save_state(state, sync_one_rms=False, sync_gyms=False, username=username, user_id=user_id)
    feedback["sheetsConnected"] = logs_saved_to_sheet if store.connected else sheets_connected()
    feedback["replacementHistorySaved"] = replacements_saved_to_sheet if replacements else True
    feedback["submissionId"] = submission_id
    feedback["saveTimingMs"] = {
        "load": load_ms,
        "duplicateCheck": duplicate_check_ms,
        "logsSheet": logs_sheet_ms,
        "replacementsSheet": replacements_sheet_ms,
        "submissionSheet": submission_sheet_ms,
        "total": int((time.perf_counter() - started_at) * 1000),
    }
    print(
        f"[finish] saved submission={submission_id or '-'} logs={len(logs)} replacements={len(replacements)} "
        f"user={username or user_id or '-'} sheet={logs_saved_to_sheet if store.connected else 'local'} load={load_ms}ms "
        f"duplicate_check={duplicate_check_ms}ms logs_sheet={logs_sheet_ms}ms "
        f"replacements_sheet={replacements_sheet_ms}ms submission_sheet={submission_sheet_ms}ms "
        f"total={feedback['saveTimingMs']['total']}ms",
        flush=True,
    )
    return jsonify(feedback)


@app.route("/api/workout/gyms", methods=["GET", "POST"])
def workout_gyms():
    username = current_request_username()
    user_id = current_request_user_id()
    state = load_gym_state(username, user_id)
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        gym = normalize_gym({
            "id": f"gym_{int(time.time() * 1000)}",
            "name": (body.get("name") or "우리동네 헬스장").strip(),
            "barbellWeight": as_float(body.get("barbellWeight"), 20.0),
            "availablePlates": body.get("availablePlates", DEFAULT_GYM["availablePlates"]),
            "dumbbellInterval": as_float(body.get("dumbbellInterval"), 2.0),
            "machineProgressionMap": {},
        })
        state["gyms"].append(gym)
        state["activeGymId"] = gym["id"]
        state["activeGymId"], state["gyms"] = normalize_gym_state(state["activeGymId"], state["gyms"])
        save_gym_state(state, username, user_id)
        return jsonify({"success": True, "activeGymId": state["activeGymId"], "gyms": state["gyms"], "activeGym": active_gym(state)})

    return jsonify({"activeGymId": state.get("activeGymId"), "gyms": state.get("gyms", [])})


@app.route("/api/workout/gyms/<gym_id>", methods=["PUT", "DELETE"])
def workout_gym_detail(gym_id):
    username = current_request_username()
    user_id = current_request_user_id()
    state = load_gym_state(username, user_id)
    gyms = state.get("gyms", [])
    gym = next((item for item in gyms if item.get("id") == gym_id), None)

    if request.method == "DELETE":
        if len(gyms) <= 1 or gym is None:
            return jsonify({"success": False, "gyms": gyms})
        state["gyms"] = [item for item in gyms if item.get("id") != gym_id]
        if state.get("activeGymId") == gym_id:
            state["activeGymId"] = state["gyms"][0]["id"]
        state["activeGymId"], state["gyms"] = normalize_gym_state(state["activeGymId"], state["gyms"])
        save_gym_state(state, username, user_id)
        return jsonify({"success": True, "gyms": state["gyms"]})

    if gym is None:
        return jsonify({"error": "gym not found"}), 404

    body = request.get_json(silent=True) or {}
    gym["name"] = (body.get("name") or gym["name"]).strip()
    gym["barbellWeight"] = as_float(body.get("barbellWeight"), gym.get("barbellWeight", 20.0))
    if "availablePlates" in body:
        gym["availablePlates"] = clean_plates(body["availablePlates"])
    gym["dumbbellInterval"] = as_float(body.get("dumbbellInterval"), gym.get("dumbbellInterval", 2.0))
    state["activeGymId"], state["gyms"] = normalize_gym_state(state["activeGymId"], state["gyms"])
    save_gym_state(state, username, user_id)
    return jsonify({"success": True, "activeGymId": state["activeGymId"], "gyms": state["gyms"], "activeGym": gym})


@app.route("/api/workout/gyms/select/<gym_id>", methods=["POST"])
def workout_gym_select(gym_id):
    username = current_request_username()
    user_id = current_request_user_id()
    state = load_gym_state(username, user_id)
    if any(gym.get("id") == gym_id for gym in state.get("gyms", [])):
        state["activeGymId"] = gym_id
        save_gym_state(state, username, user_id)
        return jsonify({"success": True, "activeGymId": state["activeGymId"], "gyms": state["gyms"], "activeGym": active_gym(state)})
    return jsonify({"success": False, "activeGymId": state.get("activeGymId"), "gyms": state.get("gyms", []), "activeGym": active_gym(state)})


@app.route("/api/workout/gyms/<gym_id>/reset-machine", methods=["POST"])
def workout_gym_reset_machine(gym_id):
    username = current_request_username()
    user_id = current_request_user_id()
    state = load_gym_state(username, user_id)
    exercise = (request.args.get("exercise") or "").strip()
    for gym in state.get("gyms", []):
        if gym.get("id") == gym_id:
            machine_map = gym.setdefault("machineProgressionMap", {})
            if exercise:
                machine_map.pop(exercise, None)
            else:
                machine_map.clear()
            save_gym_state(state, username, user_id)
            return jsonify({"success": True})
    return jsonify({"success": False}), 404


@app.route("/api/exercises")
def exercises():
    return jsonify(load_json(EXERCISE_DEFINITIONS_FILE, {}))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
