# LET'S WORKOUT 프로젝트 인수인계

마지막 정리일: 2026-09-29  
프로젝트 위치(기존 PC): `E:\AiAgent\matt-vena-powerlifting`  
GitHub: https://github.com/sjoh6136/letsworkout  
운영 URL: https://letsworkout-nm75.onrender.com

이 문서는 새 PC나 새 Codex 대화에서 프로젝트의 의도와 확정사항을 빠르게 복구하기 위한 요약이다. 세부 구현 규칙은 `AGENTS.md`, 점진적 과부하 상세는 `progression_rules.md`를 우선 확인한다.

## 1. 프로젝트 목적

개인 사용을 우선하는 iPhone 중심 웨이트 트레이닝 웹앱이다.

가장 중요한 가치는 다음과 같다.

- 정확한 운동 루틴
- 운동 중 빠른 입력과 즉각적인 반응
- 신뢰할 수 있는 점진적 과부하
- 운동명 통일과 과거 기록 연결
- Google Sheets에 안정적으로 저장되는 훈련일지
- GitHub와 Render를 통한 간단한 배포

화려한 화면보다 운동 콘텐츠와 저장 안정성이 우선이다. 기존 기능을 건드리지 않고 요청 범위만 수술적으로 수정한다.

## 2. 현재 운영 구조

- 백엔드: Flask 단일 서버 `serve.py`
- 프론트엔드: `src/main/resources/static/index.html`, `styles.css`
- 운영 DB: Google Sheets
- 저장소: GitHub `sjoh6136/letsworkout`, `main` 브랜치
- 배포: Render Python Web Service
- 주요 사용 환경: iPhone 홈 화면에 추가한 웹앱
- 최신 확인 배포 커밋: `554cc3b` (`Apply progression targets per exercise`)

Render 자동 배포가 항상 동작하지 않는다. 업데이트 요청은 아래까지 완료되어야 한다.

1. 관련 파일만 커밋
2. `origin main`에 push
3. Render에서 `Manual Deploy > Deploy latest commit`
4. `https://letsworkout-nm75.onrender.com/healthz`의 commit 값 확인

## 3. 중요 파일

| 파일 | 역할 |
|---|---|
| `serve.py` | Flask API, 인증, Google Sheets 저장, 루틴 계산 |
| `src/main/resources/static/index.html` | 메인 화면과 대부분의 프론트 로직 |
| `src/main/resources/static/styles.css` | 화면 스타일 |
| `data/routines.json` | 실제 앱이 사용하는 루틴 원본 |
| `data/routines.md` | 사람이 검토하기 위한 루틴 요약 |
| `exercise_list.md` | 운동명, 대근육/소근육 분류, 증량 정책 |
| `data/exercise_definitions.json` | 백엔드 운동 사전 |
| `src/main/resources/exercise_definitions.json` | 프론트용 운동 사전 복사본 |
| `progression_rules.md` | 점진적 과부하 확정 규칙 |
| `AGENTS.md` | 작업 범위, 검증, 배포 규칙 |

현재 배포는 오래된 Java/Spring 코드가 아니라 `serve.py`를 사용한다.

## 4. 루틴 관련 확정사항

- 2분할은 실제로 주 4회 상체/하체 회전이며 `ver.1`, `ver.2` 두 프로그램이 있다.
- 2분할의 원본 세트 수, reps 범위, RPE, 휴식시간을 유지한다.
- 복근 운동은 운동 사전에는 남기되 일반 루틴에서는 제외한다.
- RPE를 전부 8로 통일하지 않는다. 원본 루틴의 RPE 7/8/9를 그대로 사용한다.
- RDL은 하체 루틴에 둔다.
- `머신 딥스`, `머신 풀업` 명칭을 사용한다.
- 운동 교체 시 같은 부위 운동 중에서 고른다.
- 운동 교체는 해당 세션에만 적용하며 원본 루틴 JSON을 수정하지 않는다.
- 교체 운동 기록은 다음 원본 운동의 히스토리에서도 확인할 수 있어야 한다.
- 자유운동은 부위를 `가슴/등/하체/팔/어깨`로 나누고 전체 운동 종목을 유지한다.
- 유산소와 자유운동은 정규 루틴 진행도를 올리지 않는다.

운동명을 바꿀 때는 다음 파일을 함께 맞춘다.

- `data/routines.json`
- `data/routines.md`
- `exercise_list.md`
- `data/exercise_definitions.json`
- `src/main/resources/exercise_definitions.json`

운동명 불일치는 히스토리 조회와 점진적 과부하를 끊을 수 있으므로 문자열을 정확히 일치시킨다.

## 5. 점진적 과부하 핵심 규칙

Double Progression을 사용한다.

### 종목 단위 공통 목표

한 운동의 모든 세트는 동일한 목표 kg/reps를 사용한다. 실제 수행은 세트별로 저장하지만 다음 목표는 종목 전체 성공 여부로 결정한다.

예시:

```text
목표: 30kg x 8 / 8 / 8
실제: 30kg x 8 / 5 / 5
판정: 종목 실패
다음: 30kg x 8 / 8 / 8
```

`8/5/6`처럼 실패한 실제 reps에서 세트별로 증가시키면 안 된다.

### 실패 조건

아래 중 하나라도 해당하면 해당 세트는 실패다.

- 완료 체크하지 않음
- 일반 운동에서 실제 무게가 목표 무게보다 낮음
- 머신 딥스/풀업에서 실제 보조중량이 목표 보조중량보다 높음
- 실제 reps가 목표 reps보다 낮음
- 실제 RPE가 0 이하이거나 목표 RPE보다 높음
- 기본 세트 수를 완료하지 않음

한 세트라도 실패하면 종목 전체 목표를 유지한다.

### 성공 후 진행

1. 모든 세트 성공
2. 목표 reps가 범위 최대 미만이면 모든 세트 `reps + 1`
3. 목표 reps가 범위 최대면 무게를 증량하고 reps를 범위 최소로 초기화

증량 기준:

- 대근육/복합 운동: 기본 `+5kg`
- 소근육/고립 운동: 기본 `+2.5kg`
- 덤벨: 사용자가 설정한 헬스장 덤벨 간격에 맞춤
- 바벨: 보유 최소 원판의 양쪽 합계 단위에 맞춤
- 머신 딥스/풀업: 보조중량을 감소

SBD 1RM은 사용자가 직접 설정하는 고정 기준값이다. 운동 완료나 점진적 과부하가 SBD 1RM 설정을 자동으로 변경하면 안 된다. OHP는 1RM 입력 없이 이전 운동 기록으로 진행한다.

## 6. 저장과 훈련일지

Google Sheets의 공용 테이블을 username으로 필터링한다. 사용자별 `__username` 테이블은 더 이상 런타임에서 사용하지 않는다.

주요 테이블:

- `User_Accounts`
- `User_Sessions`
- `Setting_1RM`
- `Gym_Settings`
- `Workout_Logs`
- `Workout_Replacements`
- `Workout_Submissions`
- `Routine_Progress`
- `Cardio_Logs`

`Workout_Logs` A-M 컬럼 순서:

| 열 | 값 |
|---|---|
| A | 날짜 |
| B | 사용자 username |
| C | 분할 |
| D | 주차 |
| E | 일차 |
| F | 운동종목 |
| G | 세트수 |
| H | 실제 무게 |
| I | 실제 reps |
| J | 실제 RPE |
| K | SUCCESS/FAIL |
| L | 목표 무게 |
| M | 목표 reps |

중요 저장 원칙:

- 실제 입력값과 성공 판정용 목표값을 분리한다.
- 같은 `SubmissionId` 재전송은 중복 저장하지 않는다.
- `Workout_Submissions`가 idempotency를 담당한다.
- 저장 날짜는 서버 현재 시간이 아니라 운동 시작 날짜를 사용한다.
- 완료 체크 후 RPE가 비어 있으면 해당 종목 목표 RPE를 저장한다.
- Google Sheets 열을 앞쪽에 추가하거나 밀지 않는다.
- 저장 실패 시 pending 데이터를 유지하고 재시도하되 홈에 draft 배너를 상시 노출하지 않는다.

과거 주요 오류:

- SUCCESS인데 FAIL로 저장됨
- 변경한 무게가 아니라 기본 무게가 저장됨
- 한 번 저장했는데 중복 행 생성
- 저장 버튼이 장시간 `저장중...` 상태
- `_sjoh` 레거시 테이블과 공용 테이블을 동시에 조회
- 저장 후 추천 운동이 직전 완료 운동을 반영하지 않음

이 영역은 회귀 위험이 높으므로 저장 코드를 수정할 때 관련 테스트와 실제 Sheets 열 정렬을 반드시 확인한다.

## 7. 주요 사용자 기능

### 인증

- 앱 실행 시 로그인 화면 표시
- 로그인 후 세션 쿠키로 자동 로그인
- 로그아웃 전까지 로그인 유지
- 자동 로그인 확인 중 로그인 화면이 잠깐 보이는 현상을 줄이도록 설계
- 비밀번호는 salt/hash로 저장하고 평문 저장하지 않음

### 설정

- SBD 1RM 설정
- 내 헬스장 선택/추가/삭제
- 헬스장별 보유 원판과 덤벨 증량 간격
- 헬스장 설정은 최초 로그인 시 또는 설정 화면에서만 변경
- 루틴을 누를 때마다 헬스장 설정을 띄우지 않음
- 저장 버튼은 처리 중 재클릭을 막고 `저장중...` 상태 표시

### 운동 화면

- 상단에 Rest, Vol, 전체 운동 초시계, 완료 버튼
- 전체 운동 초시계는 운동 진입 즉시 시작
- Rest는 세트 완료 시 해당 종목 휴식시간으로 시작
- 종목별 휴식시간을 수정하고 다음 운동에도 기억
- 완료 버튼은 저장/중단 선택 후 처리
- 중단은 데이터 삭제 경고 후 확정
- 종목 마지막 세트 아래에 운동 교체와 세트 추가
- 추가한 세트만 스와이프로 삭제 가능하며 기본 세트는 삭제 불가
- 첫 세트의 kg/reps를 변경하면 아래 세트 입력값도 동기화하되 목표 판정값은 바꾸지 않음
- 운동 중 화면을 닫으면 draft를 저장하고 다음 실행 시 이어서 할지 확인

### 홈과 훈련일지

- 홈에서 분할 선택과 오늘 추천 운동 표시
- 각 루틴은 `루틴 보기`로 접고 펼침
- `...` 메뉴에서 프로그램을 W1D1로 다시 시작
- 리셋은 기존 운동 기록을 삭제하지 않고 진행 기준점만 갱신
- 훈련일지는 오늘 날짜를 기본으로 표시
- 달력의 `오늘` 버튼으로 현재 날짜 이동
- 운동한 날짜의 노란 표시가 운동명과 겹치지 않도록 날짜 위에 표시
- 대체 운동 기록도 원본 운동 히스토리에 연결
- 운동별 진행 그래프와 최근 기록 바텀시트 제공

### 자유운동과 유산소

- 자유운동은 운동 사전에서 부위별로 종목을 추가해 기록
- 자유운동 로그는 `Workout_Logs`에 `split=0`으로 저장
- 자유운동은 정규 루틴 진행도와 추천 순서를 변경하지 않음
- 유산소는 별도의 `Cardio_Logs`에 저장
- 유산소 화면은 경과 초시계와 완료/삭제/저장 흐름만 사용
- 유산소에는 Rest, Vol, 카운트다운 바, 목표 시간/강도를 표시하지 않음

## 8. UI 방향

- 전체 테마는 검정색과 노란색 강조색
- iPhone 한 손 조작과 숫자 가독성 우선
- 버튼과 입력값이 겹치거나 잘리지 않아야 함
- 작은 화면에서 종목명이 길어도 작업 버튼이 밀리거나 겹치지 않아야 함
- 화면 고정 상단바가 Week/Day 제목이나 모달 닫기 버튼을 가리지 않아야 함
- 탭은 즉시 반응하고 서버 응답을 기다리는 동안 UI가 멈춘 느낌을 주지 않아야 함
- 의미 없는 설명, 중복 정보, 장식 위주의 요소를 추가하지 않음
- 원판 계산/원판 보기 기능은 사용자 결정으로 삭제됨
- 신경계 피로 감지 상태 기능은 삭제됨
- 자동 휴식 타이머가 아니라 세트 완료로 시작되는 명시적 Rest 타이머를 사용

## 9. 현재 보류 또는 향후 아이디어

### iPhone 잠금화면 초시계

현재 웹/PWA만으로 잠금화면에 실시간 초시계를 표시할 수 없다.

- 웹으로 가능한 대안: 휴식 종료 시 Web Push 알림
- 실시간 잠금화면/Dynamic Island 표시: iOS 네이티브 앱 + ActivityKit Live Activity 필요
- App Store 등록 없이 Xcode로 개인 기기에 설치할 수는 있으나 Mac/Xcode가 필요

아직 구현하지 않았다.

### 추후 고려

- 유산소 기록 UX 보완
- 필요 시 네이티브 iOS 래퍼와 Live Activity
- 서비스 사용자가 늘어날 경우 Google Sheets에서 일반 DB로 이전

## 10. 검증 명령

점진적 과부하 변경 시:

```powershell
python -B -m unittest discover -s tests -v
node tests/test_progression_frontend.js
```

기본 문법 확인:

```powershell
python -m py_compile serve.py
node -e "const fs=require('fs'); const h=fs.readFileSync('src/main/resources/static/index.html','utf8'); for (const m of h.matchAll(/<script>([\\s\\S]*?)<\\/script>/g)) new Function(m[1]); console.log('js parse ok')"
```

배포 확인:

```powershell
Invoke-RestMethod -Uri 'https://letsworkout-nm75.onrender.com/healthz' -TimeoutSec 60
```

## 11. 새 PC 이전 체크리스트

1. 같은 ChatGPT 계정으로 로그인하더라도 로컬 Codex 채팅이 모두 동기화된다고 가정하지 않는다.
2. GitHub에서 `https://github.com/sjoh6136/letsworkout.git`을 clone한다.
3. 이 폴더를 Codex의 로컬 프로젝트로 연결한다.
4. `AGENTS.md`와 이 문서를 먼저 읽도록 요청한다.
5. 기존 PC의 `.env`, Google 인증 JSON 등 Git에 없는 비밀 설정을 별도로 옮긴다.
6. 기존 PC의 `E:\AiAgent\skills`에서 필요한 사용자 스킬을 옮긴다.
7. Git에 추적되지 않은 WIP/목업 파일이 필요한지 기존 PC에서 확인한다.
8. 배포 전 `git status`, 테스트, Render commit을 확인한다.

## 12. 작업 시 절대 주의할 점

- 사용자 요청과 무관한 기능을 함께 리팩터링하지 않는다.
- 기존에 정상 작동하는 저장, 입력 동기화, 인증을 깨뜨리지 않는다.
- 루틴 변경과 UI 변경을 한꺼번에 크게 섞지 않는다.
- 운동명 변경 시 사전과 루틴을 동시에 맞춘다.
- 점진적 과부하는 세트별 실제 수행값을 다음 목표로 직접 승격하지 않는다.
- 실패한 종목은 공통 목표 전체를 그대로 재제시한다.
- `_sjoh` 등 사용자별 레거시 테이블을 런타임에 다시 사용하지 않는다.
- 사용자의 허가 없이 workout log를 삭제하거나 과거 기록을 재작성하지 않는다.
- 업데이트 요청 시 GitHub push만 하고 끝내지 말고 Render와 운영 URL까지 확인한다.

## 13. 마지막 상태

2026-09-21 배포에서 점진적 과부하를 종목 단위 공통 목표로 수정했다.

검증된 사례:

```text
목표 30kg x 8회 x 3세트
실제 30kg x 8 / 5 / 5회
다음 목표 30kg x 8 / 8 / 8회
```

당시 백엔드 테스트 15개와 프론트 점진적 과부하 테스트가 통과했고, Render `/healthz`가 커밋 `554cc3b4655200340f3379a0f08166e051c483b8`을 반환했다.

새 작업을 시작할 때는 실제 GitHub HEAD와 Render `/healthz`를 다시 확인한다.

## 14. 2026-10-07 기록 화면 보완

- 종목 기록창에서 현재 운동일을 기본으로 목표 근거와 최근 그래프를 표시한다. 운동일 선택으로 A/B를 구분하며, 분할·운동일·정확한 종목명이 일치하는 기록만 집계한다.
- 훈련일지의 세트 버튼에서 실제 무게·횟수·RPE·수행 여부를 수정하거나 직전 수정을 되돌릴 수 있다. 진행 중인 운동 입력은 유지하고 다음 루틴 조회에 수정 기록을 반영한다.
- `workout_log_edits.py`는 해당 사용자의 행을 확인하고 `Workout_Logs` H–K만 수정한다. A–M 열 순서, 기존 목표 L–M, 루틴 진행도, 1RM은 변경하지 않는다.
- 수정 전후 값은 공용 `Workout_Log_Edits`에 먼저 보관한다. 열은 `EditId, Username, LogRow, ChangedAt, Before, After, Action`이다. 수정할 때만 생성하며 사용자별 레거시 탭은 사용하지 않는다.
- 기록 조회의 `sheetRow`, `rowVersion`은 응답 메타데이터이며 시트 열을 추가하지 않는다. 버전이 달라지면 덮어쓰기를 거절하며, 같은 수정 요청의 재시도는 중복 적용하지 않는다.
- 기기 대기열 저장 여부, 서버 저장 중, 재시도 대기, 서버 저장 완료를 표시한다. 이상 입력 경고 기능은 추가하지 않았다.
- 추가 프론트 코드: `src/main/resources/static/workout-history.js`. 추가 검증: `tests/test_log_edits.py`, `node tests/test_workout_history_frontend.js`.
