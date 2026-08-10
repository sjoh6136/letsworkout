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
EXERCISE_DEFINITIONS_FILE = DATA_DIR / "exercise_definitions.json"
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
STATE_CACHE_SECONDS = max(0, int(os.environ.get("STATE_CACHE_SECONDS", "20")))
APP_RELEASE = "2026-08-10-save-retry-v4"
APP_BUILD_COMMIT = os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("SOURCE_VERSION") or ""
_SHEETS_STORE = None
_AUTH_SESSION_CACHE = {}
_STATE_CACHE = {"expires_at": 0.0, "state": None}
_ROUTINES_CACHE = None
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
    USER_ACCOUNTS_TAB = "User_Accounts"
    USER_SESSIONS_TAB = "User_Sessions"
    SETTINGS_HEADER = ["Squat", "Bench", "Deadlift", "OHP", "ActiveSplit"]
    GYM_SETTINGS_HEADER = [
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
    ]
    SUBMISSIONS_HEADER = [
        "SubmissionId",
        "Date",
        "Split",
        "Week",
        "Day",
        "LogCount",
        "CreatedAt",
    ]
    LOG_HEADER = [
        "날짜",
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

    @staticmethod
    def header_matches(row, header):
        row = (row or []) + [""] * len(header)
        return [str(value).strip() for value in row[:len(header)]] == [str(value).strip() for value in header]

    def ensure_header(self, worksheet, range_name, header):
        values = worksheet.get(range_name)
        if not values or not self.header_matches(values[0], header):
            worksheet.update(values=[header], range_name=range_name)

    def ensure_tabs(self):
        settings = self.worksheet(self.SETTINGS_TAB, rows=2, cols=10)
        logs = self.worksheet(self.LOGS_TAB, rows=1000, cols=14)
        gym_settings = self.worksheet(self.GYM_SETTINGS_TAB, rows=50, cols=8)
        replacements = self.worksheet(self.REPLACEMENTS_TAB, rows=500, cols=14)
        submissions = self.worksheet(self.SUBMISSIONS_TAB, rows=500, cols=7)
        user_accounts = self.worksheet(self.USER_ACCOUNTS_TAB, rows=20, cols=10)
        user_sessions = self.worksheet(self.USER_SESSIONS_TAB, rows=100, cols=8)

        values = settings.get("A1:E2")
        if not values:
            settings.update(
                values=[self.SETTINGS_HEADER, [
                    DEFAULT_ONE_RMS["squat"],
                    DEFAULT_ONE_RMS["bench"],
                    DEFAULT_ONE_RMS["deadlift"],
                    DEFAULT_ONE_RMS["ohp"],
                    DEFAULT_ONE_RMS["activeSplit"],
                ]],
                range_name="A1:E2",
            )
        else:
            if not self.header_matches(values[0] if values else [], self.SETTINGS_HEADER):
                settings.update(values=[self.SETTINGS_HEADER], range_name="A1:E1")
            if len(values) < 2 or len(values[1]) < 5:
                row = (values[1] if len(values) > 1 else []) + [""] * 5
                settings.update(values=[[
                    row[0] or DEFAULT_ONE_RMS["squat"],
                    row[1] or DEFAULT_ONE_RMS["bench"],
                    row[2] or DEFAULT_ONE_RMS["deadlift"],
                    row[3] or DEFAULT_ONE_RMS["ohp"],
                    row[4] or DEFAULT_ONE_RMS["activeSplit"],
                ]], range_name="A2:E2")

        self.ensure_header(logs, "A1:N1", self.LOG_HEADER + ["SubmissionId", ""])
        self.ensure_header(gym_settings, "A1:G1", self.GYM_SETTINGS_HEADER)
        self.ensure_header(replacements, "A1:N1", self.REPLACEMENTS_HEADER)
        self.ensure_header(submissions, "A1:G1", self.SUBMISSIONS_HEADER)
        self.ensure_header(user_accounts, "A1:I1", self.USER_ACCOUNTS_HEADER)
        self.ensure_header(user_sessions, "A1:G1", self.USER_SESSIONS_HEADER)

    def load_one_rms(self):
        settings = self.worksheet(self.SETTINGS_TAB, rows=2, cols=10)
        row = (settings.get("A2:E2") or [[]])[0]
        row = row + [""] * 5
        return {
            "squat": sheet_float(row[0], DEFAULT_ONE_RMS["squat"]),
            "bench": sheet_float(row[1], DEFAULT_ONE_RMS["bench"]),
            "deadlift": sheet_float(row[2], DEFAULT_ONE_RMS["deadlift"]),
            "ohp": sheet_float(row[3], DEFAULT_ONE_RMS["ohp"]),
            "activeSplit": sheet_int(row[4], DEFAULT_ONE_RMS["activeSplit"]),
        }

    def save_one_rms(self, one_rms):
        settings = self.worksheet(self.SETTINGS_TAB, rows=2, cols=10)
        settings.update(values=[self.SETTINGS_HEADER], range_name="A1:E1")
        settings.update(values=[[
            sheet_float(one_rms.get("squat"), DEFAULT_ONE_RMS["squat"]),
            sheet_float(one_rms.get("bench"), DEFAULT_ONE_RMS["bench"]),
            sheet_float(one_rms.get("deadlift"), DEFAULT_ONE_RMS["deadlift"]),
            sheet_float(one_rms.get("ohp"), DEFAULT_ONE_RMS["ohp"]),
            sheet_int(one_rms.get("activeSplit"), DEFAULT_ONE_RMS["activeSplit"]),
        ]], range_name="A2:E2")

    def load_gyms(self):
        gym_settings = self.worksheet(self.GYM_SETTINGS_TAB, rows=50, cols=8)
        rows = gym_settings.get("A2:G")
        gyms = []
        active_gym_id = None

        for row in rows:
            row = row + [""] * 7
            if not row[1] and not row[2]:
                continue

            gym = normalize_gym({
                "id": row[1],
                "name": row[2],
                "barbellWeight": sheet_float(row[3], DEFAULT_GYM["barbellWeight"]),
                "availablePlates": sheet_json(row[4], DEFAULT_GYM["availablePlates"]),
                "dumbbellInterval": sheet_float(row[5], DEFAULT_GYM["dumbbellInterval"]),
                "machineProgressionMap": sheet_json(row[6], {}),
            })
            gyms.append(gym)
            if sheet_bool(row[0]):
                active_gym_id = gym["id"]

        if not gyms:
            return None, []
        return normalize_gym_state(active_gym_id, gyms)

    def save_gyms(self, active_gym_id, gyms):
        active_gym_id, gyms = normalize_gym_state(active_gym_id, gyms)
        gym_settings = self.worksheet(self.GYM_SETTINGS_TAB, rows=max(50, len(gyms) + 1), cols=8)
        rows = [self.GYM_SETTINGS_HEADER]
        for gym in gyms:
            rows.append([
                "TRUE" if gym.get("id") == active_gym_id else "",
                gym.get("id", ""),
                gym.get("name", ""),
                as_float(gym.get("barbellWeight"), DEFAULT_GYM["barbellWeight"]),
                json.dumps(clean_plates(gym.get("availablePlates")), ensure_ascii=False),
                as_float(gym.get("dumbbellInterval"), DEFAULT_GYM["dumbbellInterval"]),
                json.dumps(gym.get("machineProgressionMap") or {}, ensure_ascii=False),
            ])
        gym_settings.clear()
        gym_settings.update(values=rows, range_name=f"A1:G{len(rows)}")
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

    def load_logs(self):
        logs = self.worksheet(self.LOGS_TAB, rows=1000, cols=14)
        rows = logs.get("A2:N")
        parsed = []
        for row in rows:
            log = self.parse_log_row(row)
            if log:
                parsed.append(log)
        return parsed

    def parse_log_row(self, row):
        row = [str(value).strip() for value in row]
        start = next((idx for idx, value in enumerate(row) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)), None)
        if start is None:
            return None
        row = row + [""] * (start + 13 - len(row))
        if len(row) - start < 12 or not row[start]:
            return None
        return {
            "date": row[start],
            "split": sheet_int(row[start + 1]),
            "week": sheet_int(row[start + 2], 1),
            "day": row[start + 3],
            "exercise": row[start + 4],
            "setNo": sheet_int(row[start + 5], 1),
            "weight": sheet_float(row[start + 6]),
            "reps": sheet_int(row[start + 7]),
            "rpe": sheet_float(row[start + 8]),
            "status": row[start + 9] or "FAIL",
            "targetWeight": sheet_float(row[start + 10], sheet_float(row[start + 6])),
            "targetReps": sheet_int(row[start + 11], sheet_int(row[start + 7])),
            "submissionId": row[start + 12],
        }

    def append_logs(self, logs):
        if not logs:
            return True
        worksheet = self.worksheet(self.LOGS_TAB, rows=1000, cols=14)
        rows = []
        for log in logs:
            rows.append([
                log.get("date", ""),
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
                log.get("submissionId", ""),
            ])
        worksheet.append_rows(rows, value_input_option="RAW", table_range="A1:M1")
        return True

    def load_log_submission_ids(self):
        worksheet = self.worksheet(self.LOGS_TAB, rows=1000, cols=14)
        rows = worksheet.get("M2:M")
        return {str(row[0]).strip() for row in rows if row and str(row[0]).strip()}

    def load_replacements(self):
        worksheet = self.worksheet(self.REPLACEMENTS_TAB, rows=500, cols=14)
        rows = worksheet.get("A2:N")
        parsed = []
        for row in rows:
            row = [str(value).strip() for value in row] + [""] * 14
            if not row[0] or not row[4] or not row[5]:
                continue
            parsed.append({
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
            })
        return parsed

    def append_replacements(self, replacements):
        if not replacements:
            return True
        worksheet = self.worksheet(self.REPLACEMENTS_TAB, rows=500, cols=14)
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
            ])
        worksheet.append_rows(rows, value_input_option="RAW", table_range="A1:N1")
        return True

    def load_submission_ids(self):
        worksheet = self.worksheet(self.SUBMISSIONS_TAB, rows=500, cols=7)
        rows = worksheet.get("A2:A")
        return {str(row[0]).strip() for row in rows if row and str(row[0]).strip()}

    def append_submission(self, submission):
        submission_id = str(submission.get("id") or "").strip()
        if not submission_id:
            return True
        worksheet = self.worksheet(self.SUBMISSIONS_TAB, rows=500, cols=7)
        worksheet.append_row([
            submission_id,
            submission.get("date", ""),
            submission.get("split", ""),
            submission.get("week", ""),
            submission.get("day", ""),
            submission.get("logCount", ""),
            submission.get("createdAt", ""),
        ], value_input_option="RAW", table_range="A1:G1")
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


def cached_state():
    if STATE_CACHE_SECONDS <= 0:
        return None
    state = _STATE_CACHE.get("state")
    if state is None or _STATE_CACHE.get("expires_at", 0) <= time.time():
        return None
    return copy.deepcopy(state)


def set_state_cache(state):
    if STATE_CACHE_SECONDS <= 0:
        return
    _STATE_CACHE["state"] = copy.deepcopy(state)
    _STATE_CACHE["expires_at"] = time.time() + STATE_CACHE_SECONDS


def invalidate_state_cache():
    _STATE_CACHE["state"] = None
    _STATE_CACHE["expires_at"] = 0.0


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


def append_workout_logs_to_sheet(logs):
    store = sheets_store()
    if not store.connected:
        return False
    try:
        return store.append_logs(logs)
    except Exception as exc:
        print(f"[warn] failed to append workout logs to Google Sheets: {exc}")
        return False


def append_workout_replacements_to_sheet(replacements):
    store = sheets_store()
    if not store.connected:
        return False
    try:
        return store.append_replacements(replacements)
    except Exception as exc:
        print(f"[warn] failed to append workout replacements to Google Sheets: {exc}")
        return False


def append_workout_submission_to_sheet(submission):
    store = sheets_store()
    if not store.connected:
        return False
    try:
        return store.append_submission(submission)
    except Exception as exc:
        print(f"[warn] failed to append workout submission marker to Google Sheets: {exc}")
        return False


def replacement_key(item):
    return "|".join([
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


def sheet_has_submission(submission_id):
    if not submission_id:
        return False
    store = sheets_store()
    if not store.connected:
        return False
    try:
        if submission_id in store.load_submission_ids():
            return True
    except Exception as exc:
        print(f"[warn] failed to load workout submission markers: {exc}")
    try:
        return submission_id in store.load_log_submission_ids()
    except Exception as exc:
        print(f"[warn] failed to load workout log submission markers: {exc}")
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


def load_legacy_gyms():
    legacy = load_json(GYM_SETTINGS_FILE, {})
    gyms = legacy.get("gyms") if isinstance(legacy, dict) else None
    if isinstance(gyms, list) and gyms:
        return legacy.get("activeGymId") or gyms[0].get("id"), gyms
    return DEFAULT_GYM["id"], [copy.deepcopy(DEFAULT_GYM)]


def load_file_state():
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


def load_state(force_refresh=False):
    if not force_refresh:
        state = cached_state()
        if state is not None:
            return state

    state = load_file_state()
    store = sheets_store()
    if store.connected:
        try:
            state["oneRms"].update(store.load_one_rms())
            state["logs"] = store.load_logs()
        except Exception as exc:
            print(f"[warn] failed to load Google Sheets state, using local file state: {exc}")
        try:
            state["replacements"] = merge_replacements(state.get("replacements", []), store.load_replacements())
        except Exception as exc:
            print(f"[warn] failed to load replacement history from Google Sheets, using local file state: {exc}")
        try:
            active_gym_id, gyms = store.load_gyms()
            if gyms:
                state["activeGymId"], state["gyms"] = active_gym_id, gyms
            else:
                state["activeGymId"], state["gyms"] = normalize_gym_state(DEFAULT_GYM["id"], [copy.deepcopy(DEFAULT_GYM)])
                store.save_gyms(state.get("activeGymId"), state.get("gyms", []))
        except Exception as exc:
            print(f"[warn] failed to load gym settings from Google Sheets, using local file state: {exc}")
    set_state_cache(state)
    return state


def save_state(state, sync_one_rms=True, sync_gyms=True) -> None:
    state["activeGymId"], state["gyms"] = normalize_gym_state(state.get("activeGymId"), state.get("gyms"))
    store = sheets_store()
    if store.connected:
        if sync_one_rms:
            try:
                store.save_one_rms(state.get("oneRms", {}))
            except Exception as exc:
                print(f"[warn] failed to save 1RM to Google Sheets: {exc}")
        if sync_gyms:
            try:
                store.save_gyms(state.get("activeGymId"), state.get("gyms", []))
            except Exception as exc:
                print(f"[warn] failed to save gym settings to Google Sheets: {exc}")
    save_json(STATE_FILE, state)
    set_state_cache(state)


def load_gym_state():
    state = load_file_state()
    store = sheets_store()
    if store.connected:
        try:
            active_gym_id, gyms = store.load_gyms()
            if gyms:
                state["activeGymId"], state["gyms"] = active_gym_id, gyms
        except Exception as exc:
            print(f"[warn] failed to load gym settings from Google Sheets, using local file state: {exc}")
    state["activeGymId"], state["gyms"] = normalize_gym_state(state.get("activeGymId"), state.get("gyms"))
    return state


def save_gym_state(state) -> None:
    state["activeGymId"], state["gyms"] = normalize_gym_state(state.get("activeGymId"), state.get("gyms"))
    store = sheets_store()
    if store.connected:
        try:
            store.save_gyms(state.get("activeGymId"), state.get("gyms", []))
        except Exception as exc:
            print(f"[warn] failed to save gym settings to Google Sheets: {exc}")
    save_json(STATE_FILE, state)
    invalidate_state_cache()


def load_routines():
    global _ROUTINES_CACHE
    if _ROUTINES_CACHE is not None:
        return copy.deepcopy(_ROUTINES_CACHE)

    routines = load_json(ROUTINES_FILE, {})
    if not isinstance(routines, dict):
        routines = {}
    _ROUTINES_CACHE = routines
    return copy.deepcopy(_ROUTINES_CACHE)


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
    rpe_ok = rpe <= target_rpe if rpe > 0 else str(log.get("status", "")).upper() == "SUCCESS"
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
                    prev_target_reps = as_int(prev_last.get("targetReps"), min_reps)

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


def workout_status_payload(state, routines=None):
    active_split = as_int(state["oneRms"].get("activeSplit"), 5)
    routines = routines or load_routines()
    routine_days = routines.get(str(active_split), [])
    routine_day_count = len(routine_days) or active_split
    next_recommended = "Day 1"
    last_completed = None

    for log in reversed(state.get("logs", [])):
        if log.get("split") == active_split:
            last_num = day_number(log.get("day"))
            last_completed = f"Day {last_num}"
            next_num = last_num + 1 if last_num < routine_day_count else 1
            next_recommended = f"Day {next_num}"
            break

    return {
        "sheetsConnected": sheets_connected(),
        "routineDayCount": routine_day_count,
        "lastCompletedDay": last_completed,
        "nextRecommendedDay": next_recommended,
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


def normalize_logs(raw_logs, split, week, day_id, exercise_defs=None, submission_id=""):
    today = today_iso()
    normalized = []
    exercise_defs = exercise_defs or {}
    for raw in raw_logs or []:
        log = dict(raw)
        log["date"] = log.get("date") or today
        log["submissionId"] = str(log.get("submissionId") or submission_id or "").strip()
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
    }


def normalize_replacements(raw_replacements, split, week, day_id, date, submission_id):
    normalized = []
    for raw in raw_replacements or []:
        item = normalize_replacement_item({
            **(raw if isinstance(raw, dict) else {}),
            "date": date,
            "split": split,
            "week": week,
            "day": day_id,
            "submissionId": submission_id,
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
            if core_type in {"squat", "bench", "deadlift"}:
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
    state = load_state()
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        for key, default in DEFAULT_ONE_RMS.items():
            if key in body:
                state["oneRms"][key] = bool(body[key]) if isinstance(default, bool) else as_float(body[key], default)
        state["oneRms"]["activeSplit"] = as_int(state["oneRms"].get("activeSplit"), 5)
        save_state(state)
        return jsonify(state["oneRms"])

    return jsonify({"oneRms": state["oneRms"], "sheetsConnected": sheets_connected()})


@app.route("/api/workout/bootstrap")
def workout_bootstrap():
    state = load_state()
    routines = load_routines()
    return jsonify({
        "oneRms": state["oneRms"],
        "sheetsConnected": sheets_connected(),
        "gyms": state.get("gyms", []),
        "activeGymId": state.get("activeGymId"),
        "exerciseDefinitions": load_json(EXERCISE_DEFINITIONS_FILE, {}),
        "routine": apply_progression(routines, state),
        "status": workout_status_payload(state, routines),
        "logs": state.get("logs", []),
        "replacements": state.get("replacements", []),
    })


@app.route("/api/workout/routine")
def workout_routine():
    state = load_state()
    return jsonify(apply_progression(load_routines(), state))


@app.route("/api/workout/status")
def workout_status():
    state = load_state()
    return jsonify(workout_status_payload(state))


@app.route("/api/workout/logs")
def workout_logs():
    return jsonify(load_state().get("logs", []))


@app.route("/api/workout/replacements")
def workout_replacements():
    return jsonify(load_state().get("replacements", []))


@app.route("/api/workout/finish", methods=["POST"])
def workout_finish():
    started_at = time.perf_counter()
    state = load_state()
    load_ms = int((time.perf_counter() - started_at) * 1000)
    body = request.get_json(silent=True) or {}
    split = as_int(body.get("split"), as_int(state["oneRms"].get("activeSplit"), 5))
    week = as_int(body.get("week"), 1)
    day_id = body.get("day") or "Day 1"
    submission_id = str(body.get("submissionId") or "").strip()
    date = today_iso()
    exercise_defs = routine_exercise_lookup(load_routines(), split)
    logs = normalize_logs(body.get("logs", []), split, week, day_id, exercise_defs, submission_id)
    for log in logs:
        log["date"] = date
    replacements = normalize_replacements(body.get("replacements", []), split, week, day_id, date, submission_id)

    duplicate_check_started_at = time.perf_counter()
    is_duplicate = submission_id and (state_has_submission(state, submission_id) or sheet_has_submission(submission_id))
    duplicate_check_ms = int((time.perf_counter() - duplicate_check_started_at) * 1000)
    if is_duplicate:
        known_keys = {replacement_key(item) for item in state.get("replacements", [])}
        missing_replacements = [item for item in replacements if replacement_key(item) not in known_keys]
        if missing_replacements:
            append_workout_replacements_to_sheet(missing_replacements)
            state["replacements"] = merge_replacements(state.get("replacements", []), missing_replacements)
            save_state(state, sync_one_rms=False, sync_gyms=False)
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
        logs_saved_to_sheet = append_workout_logs_to_sheet(logs)
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
        replacements_saved_to_sheet = append_workout_replacements_to_sheet(replacements)
        replacements_sheet_ms = int((time.perf_counter() - replacements_started_at) * 1000)

    one_rms_before = copy.deepcopy(state.get("oneRms", {}))
    feedback = evaluate_and_update(state, logs, split, week, day_id)
    one_rms_changed = state.get("oneRms", {}) != one_rms_before
    state["logs"].extend(logs)
    state["replacements"] = merge_replacements(state.get("replacements", []), replacements)
    submission_sheet_ms = 0
    if submission_id:
        submission = make_submission_record(submission_id, date, split, week, day_id, len(logs))
        remember_submission(state, submission)
        submission_started_at = time.perf_counter()
        append_workout_submission_to_sheet(submission)
        submission_sheet_ms = int((time.perf_counter() - submission_started_at) * 1000)
    save_state(state, sync_one_rms=one_rms_changed, sync_gyms=False)
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
        f"sheet={logs_saved_to_sheet if store.connected else 'local'} load={load_ms}ms "
        f"duplicate_check={duplicate_check_ms}ms logs_sheet={logs_sheet_ms}ms "
        f"replacements_sheet={replacements_sheet_ms}ms submission_sheet={submission_sheet_ms}ms "
        f"total={feedback['saveTimingMs']['total']}ms",
        flush=True,
    )
    return jsonify(feedback)


@app.route("/api/workout/gyms", methods=["GET", "POST"])
def workout_gyms():
    state = load_gym_state()
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
        save_gym_state(state)
        return jsonify({"success": True, "activeGymId": state["activeGymId"], "gyms": state["gyms"], "activeGym": active_gym(state)})

    return jsonify({"activeGymId": state.get("activeGymId"), "gyms": state.get("gyms", [])})


@app.route("/api/workout/gyms/<gym_id>", methods=["PUT", "DELETE"])
def workout_gym_detail(gym_id):
    state = load_gym_state()
    gyms = state.get("gyms", [])
    gym = next((item for item in gyms if item.get("id") == gym_id), None)

    if request.method == "DELETE":
        if len(gyms) <= 1 or gym is None:
            return jsonify({"success": False, "gyms": gyms})
        state["gyms"] = [item for item in gyms if item.get("id") != gym_id]
        if state.get("activeGymId") == gym_id:
            state["activeGymId"] = state["gyms"][0]["id"]
        state["activeGymId"], state["gyms"] = normalize_gym_state(state["activeGymId"], state["gyms"])
        save_gym_state(state)
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
    save_gym_state(state)
    return jsonify({"success": True, "activeGymId": state["activeGymId"], "gyms": state["gyms"], "activeGym": gym})


@app.route("/api/workout/gyms/select/<gym_id>", methods=["POST"])
def workout_gym_select(gym_id):
    state = load_gym_state()
    if any(gym.get("id") == gym_id for gym in state.get("gyms", [])):
        state["activeGymId"] = gym_id
        save_gym_state(state)
        return jsonify({"success": True, "activeGymId": state["activeGymId"], "gyms": state["gyms"], "activeGym": active_gym(state)})
    return jsonify({"success": False, "activeGymId": state.get("activeGymId"), "gyms": state.get("gyms", []), "activeGym": active_gym(state)})


@app.route("/api/workout/gyms/<gym_id>/reset-machine", methods=["POST"])
def workout_gym_reset_machine(gym_id):
    state = load_gym_state()
    exercise = (request.args.get("exercise") or "").strip()
    for gym in state.get("gyms", []):
        if gym.get("id") == gym_id:
            machine_map = gym.setdefault("machineProgressionMap", {})
            if exercise:
                machine_map.pop(exercise, None)
            else:
                machine_map.clear()
            save_gym_state(state)
            return jsonify({"success": True})
    return jsonify({"success": False}), 404


@app.route("/api/exercises")
def exercises():
    return jsonify(load_json(EXERCISE_DEFINITIONS_FILE, {}))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
