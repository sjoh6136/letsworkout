# AGENTS.md

## Project Goal

LET'S WORKOUT is a personal iPhone-first workout tracking web app.

The core value of this project is not decoration. It is:

- accurate routines
- fast workout logging
- stable progressive overload
- exercise names that do not break history matching
- simple deployment that keeps working

This is a single-user app for now. Prefer simple, obvious code over generalized systems.

## Current Production

- Live app: https://letsworkout-nm75.onrender.com
- GitHub repo: https://github.com/sjoh6136/letsworkout
- Backend runtime: Render Python web service
- Database: Google Sheets
- Main user device target: iPhone

Render automatic deploy may not reliably trigger. After pushing to GitHub, the Render dashboard may need:

```text
Manual Deploy > Deploy latest commit
```

## Architecture

The active app is a Flask backend serving a static HTML/CSS/JS frontend.

Important files:

- `serve.py`: main Flask API and static file server
- `src/main/resources/static/index.html`: main UI and frontend logic
- `src/main/resources/static/styles.css`: app styling
- `data/routines.json`: source of truth for routines used by the app
- `data/routines.md`: human-readable routine summary
- `exercise_list.md`: exercise naming, muscle classification, increment policy
- `data/exercise_definitions.json`: backend exercise dictionary
- `src/main/resources/exercise_definitions.json`: mirrored/static exercise dictionary
- `progression_rules.md`: progressive overload behavior
- `render.yaml`: Render service definition

There are older Java/Spring files in `src/main/java`, but the current deployed app runs through `serve.py`.

## Source Of Truth

For routines, `data/routines.json` is the source of truth.

When changing routines, keep these aligned:

- `data/routines.json`
- `data/routines.md`
- `exercise_list.md`
- `data/exercise_definitions.json`
- `src/main/resources/exercise_definitions.json`

If an exercise name appears in a routine but not in the exercise dictionary, progression logic may fail or use the wrong increment.

## Routine Rules

- All routine `rpeTarget` values must be `8.0`.
- Do not reintroduce `8.5` or `9.0` unless the user explicitly asks.
- SBD is the only 1RM-based target system. OHP must progress from previous workout history, not from an OHP 1RM input.
- 2-day split means a 4-day upper/lower rotation:
  - Day 1: upper A
  - Day 2: lower A
  - Day 3: upper B
  - Day 4: lower B
- 3-day split is Push / Pull / Legs.
- 4-day split is chest+triceps / back+biceps / legs / shoulders+arms.
- 5-day split is chest / back / shoulders / legs / arms+abs.
- Use machine names for dip and pull-up variants:
  - `머신 딥스`
  - `머신 풀업`
- Do not use old routine names:
  - `딥스 (Dips)`
  - `풀업`
  - `풀업 또는 랫 풀 다운`

## RDL Policy

The user may think of Romanian deadlift as a back-involved movement because the spinal erectors work hard.

For this app, keep `루마니안 데드리프트` on lower/legs days unless the user explicitly changes the programming. The local Jeff Nippard reference places RDL in lower/legs contexts, and the app treats it as a hip-hinge movement mainly for hamstrings/glutes.

## Progressive Overload Rules

The app uses double progression.

Progression sequence:

1. Increase reps first within the target rep range.
2. When reps reach the top of the range, increase weight.
3. After weight increases, reset target reps to the bottom of the range.

Success requires:

- target reps reached
- set completed
- actual RPE <= target RPE

Current increment policy:

- compound / large-muscle movements: `+5kg`
- isolation / small-muscle movements: `+2.5kg`

The increment comes from exercise classification, so exact exercise naming matters.

## Google Sheets Rules

Google Sheets is the production database.

Main spreadsheet:

```text
1EZYNSFxd7iuEbKRCNSYyB-rVHz72TkS4TOAJcUxabBA
```

Workout log column order is important. Do not add an empty leading column or shift columns.

`Workout_Logs` schema:

| Column | Field |
|---|---|
| A | 날짜 |
| B | 분할 |
| C | 주차 |
| D | 일차 |
| E | 운동종목 |
| F | 세트수 |
| G | 무게(kg) |
| H | 횟수(reps) |
| I | RPE |
| J | 상태 |
| K | 목표무게(kg) |
| L | 목표횟수(reps) |

M/N and later columns are not part of the normal log schema.

Gym equipment settings are stored in a separate `Gym_Settings` tab. Keep it separate from `Workout_Logs` so workout log columns never shift.

Login data is stored separately:

- `User_Accounts`: username, display name, password salt/hash, account metadata
- `User_Sessions`: hashed session tokens and expiry/revocation metadata

Never store plaintext passwords. Do not place auth/session columns in `Workout_Logs`.

## Backend Coding Rules

- Keep `serve.py` straightforward.
- Avoid large framework changes.
- Keep API responses stable unless frontend code is updated in the same change.
- `/api/workout/routine` returns routines with progression-applied targets.
- `/api/workout/status` recommends the next workout day.
- Recommendation logic must use the actual routine day count, not the split number.
- `/api/workout/finish` saves workout logs and evaluates progression.
- `/api/auth/status`, `/api/auth/register`, `/api/auth/login`, and `/api/auth/logout` are public auth endpoints.
- Other `/api/*` endpoints require the `lw_session` cookie.
- Be careful around Google Sheets write paths. Column alignment regressions are high risk.

## Frontend Coding Rules

The app is used during workouts, mostly on iPhone.

Prioritize:

- instant tap feedback
- compact layout
- readable numbers
- one-hand input flow
- low friction during sets

Avoid:

- waiting for a server response before showing a UI state change
- long text blocks inside the app
- decorative UI that slows down logging
- duplicated information in workout rows
- input layouts where values are clipped on mobile

For split selection and similar actions, update UI first and save in the background when safe.

## Data Editing Rules

When editing `data/routines.json`:

- Keep valid JSON.
- Keep `rpeTarget` as `8.0`.
- Make sure each exercise name exists in both exercise definition JSON files.
- Update `data/routines.md` so the user can review routines easily.
- Keep Korean exercise names consistent.
- Keep machine replacements consistent.

When adding a new exercise:

1. Add it to `exercise_list.md`.
2. Classify it as compound or isolation.
3. Add it to `data/exercise_definitions.json`.
4. Add it to `src/main/resources/exercise_definitions.json`.
5. Use the exact same string in routines.

## Validation Checklist

Before finishing code or data changes, run the relevant checks.

Python syntax:

```bash
python -m py_compile serve.py
```

Frontend script parse check:

```bash
node -e "const fs=require('fs'); const h=fs.readFileSync('src/main/resources/static/index.html','utf8'); for (const m of h.matchAll(/<script>([\\s\\S]*?)<\\/script>/g)) new Function(m[1]); console.log('js parse ok')"
```

Routine JSON parse and RPE check:

```powershell
$r = Get-Content -Raw -Encoding UTF8 -LiteralPath 'data/routines.json' | ConvertFrom-Json
$r.PSObject.Properties.Name | ForEach-Object { $split = $_; $r.$split | ForEach-Object { $_.exercises } } | Group-Object rpeTarget
```

Exercise dictionary check:

```powershell
$r = Get-Content -Raw -Encoding UTF8 -LiteralPath 'data/routines.json' | ConvertFrom-Json
$defs = Get-Content -Raw -Encoding UTF8 -LiteralPath 'data/exercise_definitions.json' | ConvertFrom-Json
$known = @{}
foreach ($n in $defs.large_muscles) { $known[$n] = $true }
foreach ($n in $defs.small_muscles) { $known[$n] = $true }
$missing = @()
foreach ($split in $r.PSObject.Properties.Name) {
  foreach ($day in $r.$split) {
    foreach ($ex in $day.exercises) {
      if (-not $known.ContainsKey($ex.name)) {
        $missing += "$split $($day.id) $($ex.name)"
      }
    }
  }
}
if ($missing.Count) { $missing; exit 1 } else { 'routine/exercise dictionary ok' }
```

Live deploy check:

```powershell
$auth = Invoke-RestMethod -Uri 'https://letsworkout-nm75.onrender.com/api/auth/status' -TimeoutSec 30
$auth | ConvertTo-Json -Compress
```

Routine data expectations when checking with an authenticated API session or local `data/routines.json`:

```text
2:4
3:3
4:4
5:5
```

Expected RPE values:

```text
8.0 only
```

## Deployment Checklist

1. Confirm `git status --short`.
2. Run local validation.
3. Commit relevant files.
4. Push to `origin main`.
5. If Render does not auto-deploy, run `Manual Deploy > Deploy latest commit`.
6. Verify live API.

For routine changes, verify the live API contains the new exercise names and no old names.

## Git Rules

- Check `git status --short` before edits.
- Do not revert user changes unless explicitly asked.
- Keep commits focused.
- Do not use destructive git commands such as `git reset --hard` unless explicitly requested.
- Commit and push deployable changes when the user expects the web app to update.
- Documentation-only changes do not require Render deploy, but should still be committed if they belong in the repo.

## Known Gotchas

- Render may continue serving the old commit until manually deployed.
- Render free instances can spin down; first request after inactivity may be slow.
- Google Sheets append alignment can break if blank leading cells are introduced.
- `src/main/resources/exercise_definitions.json` may drift from `data/exercise_definitions.json`; keep both synchronized.
- Routine names must be exact strings. Small name differences can break progression continuity.
- The app has a simple login system. First account creation is allowed only while `User_Accounts` is empty.

## Do Not

- Do not add exercises to routines without adding them to the exercise dictionaries.
- Do not change `rpeTarget` away from `8.0` without explicit instruction.
- Do not reintroduce `딥스 (Dips)`, `풀업`, or `풀업 또는 랫 풀 다운` into routines.
- Do not shift Google Sheets columns.
- Do not make UI changes that slow down workout logging.
- Do not introduce new frameworks for small fixes.
- Do not prioritize visual polish over routine correctness.
