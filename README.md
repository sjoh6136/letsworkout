# Matt Vena Powerlifting

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/sjoh6136/letsworkout)

개인용 운동 루틴/기록 웹앱입니다. 현재 실제 실행 경로는 `serve.py` 하나로 통일되어 있고, Flask가 정적 UI와 API를 같이 제공합니다.

## 로컬 실행

```powershell
pip install -r requirements.txt
python serve.py
```

브라우저에서는 `http://localhost:8080`으로 접속합니다. iPhone에서 테스트할 때는 PC와 같은 Wi-Fi에 연결한 뒤 `http://PC_IP:8080`으로 접속합니다.

## 주요 파일

- `serve.py`: Flask 서버/API
- `src/main/resources/static/index.html`: 앱 화면
- `src/main/resources/static/styles.css`: 앱 스타일
- `data/routines.json`: 2~5분할 루틴
- `data/exercise_definitions.json`: 운동별 증량 기준
- `data/app_state.json`: 개인 기록/1RM/헬스장 설정, GitHub에 올리지 않음

## Render 배포

Render Web Service에서 아래 설정을 사용합니다.

```text
Build Command: pip install -r requirements.txt
Start Command: gunicorn serve:app --bind 0.0.0.0:$PORT
Health Check Path: /healthz
```

환경 변수는 아래처럼 설정합니다.

```text
APP_TIMEZONE=Asia/Seoul
APP_DATA_DIR=/var/data
```

개인 기록을 유지하려면 Render Persistent Disk를 추가하고 mount path를 `/var/data`로 설정합니다.

처음 테스트 배포는 `render.yaml` 기준으로 `/tmp/letsworkout-data`에 기록합니다. 이 방식은 빠르게 띄우기 좋지만 Render 재시작/재배포 시 기록이 사라질 수 있습니다. 기록을 유지하려면 Render 서비스 생성 후 Persistent Disk를 붙이고 `APP_DATA_DIR`을 `/var/data`로 바꿉니다.
