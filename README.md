# Matt Vena Powerlifting

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/sjoh6136/letsworkout)

개인용 운동 루틴/기록 웹앱입니다. 현재 실행 진입점은 `serve.py` 하나이며, Flask가 정적 UI와 API를 함께 제공합니다.

## 로컬 실행

```powershell
pip install -r requirements.txt
python serve.py
```

브라우저에서 `http://localhost:8080`으로 접속합니다. iPhone에서 테스트할 때는 PC와 같은 Wi-Fi에 연결한 뒤 `http://PC_IP:8080`으로 접속합니다.

## Google Sheets 저장소

운동 기록, SBD 1RM 설정, 헬스장 장비 설정은 Google Sheets를 기준 저장소로 사용합니다.

- Spreadsheet ID: `1EZYNSFxd7iuEbKRCNSYyB-rVHz72TkS4TOAJcUxabBA`
- 1RM/분할 설정 탭: `Setting_1RM`
- 운동 로그 탭: `Workout_Logs`
- 헬스장 설정 탭: `Gym_Settings`

로컬에서는 루트의 `credentials.json`을 읽습니다. 이 파일은 GitHub에 올리지 않습니다.

Render에서는 서비스의 `Environment` 메뉴에서 아래 중 하나를 설정합니다.

- 권장: `GOOGLE_APPLICATION_CREDENTIALS_JSON` 환경변수에 `credentials.json` 전체 내용을 붙여넣기
- 대안: Secret File로 `credentials.json`을 업로드

필수 환경변수:

```text
GOOGLE_SHEETS_SPREADSHEET_ID=1EZYNSFxd7iuEbKRCNSYyB-rVHz72TkS4TOAJcUxabBA
APP_TIMEZONE=Asia/Seoul
```

Google Sheets 연결에 실패하면 앱은 기존처럼 로컬 JSON 파일에 임시 저장합니다.

## Render 배포

```text
Build Command: pip install -r requirements.txt
Start Command: gunicorn serve:app --bind 0.0.0.0:$PORT
Health Check Path: /healthz
```

Render 무료 인스턴스는 유휴 상태에서 잠들 수 있으므로 첫 접속이 느리거나 일시적으로 실패할 수 있습니다.
