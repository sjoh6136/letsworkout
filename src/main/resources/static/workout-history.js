// Small additions to the existing history and save flows.
let historySourceExercise = null;
let savedLogEditor = null;
let workoutSaveStateTimer = null;

function showWorkoutSaveState(message, completed = false) {
    const el = document.getElementById("workout-save-state");
    if (!el) return;
    clearTimeout(workoutSaveStateTimer);
    el.textContent = message;
    el.hidden = !message;
    if (completed) workoutSaveStateTimer = setTimeout(() => { el.hidden = true; }, 6000);
}

function describeProgression(ex, dayId) {
    const previous = latestExerciseSessionLogs(ex.name, dayId);
    if (!previous.length) return "이 운동일의 이전 기록 없음 · 루틴 기본값과 설정한 1RM/장비 기준 목표입니다.";
    const [minReps, maxReps] = parseRepsRangeFrontend(ex.repsRange);
    const weights = previous.map(log => Number(log.targetWeight ?? log.weight) || 0);
    const weight = isAssistedMachineExercise(ex.name) ? Math.min(...weights) : Math.max(...weights);
    const reps = clampTargetRepsFrontend(Math.max(minReps, ...previous.map(log => parseInt(log.targetReps) || minReps)), minReps, maxReps);
    const rpe = Number(ex.rpeTarget) || 8;
    const failures = previous.filter(log => !setSucceededFrontend({
        exercise: ex.name, completed: String(log.status || "").toUpperCase() === "SUCCESS",
        weight: log.weight, targetWeight: weight, reps: log.reps, targetReps: reps,
        rpe: log.rpe, targetRpe: rpe
    }));
    const enoughSets = previous.length >= Number(ex.baseSets || ex.sets);
    const actual = `이전 수행 ${summarizeSessionLogs(previous)}`;
    const target = `이전 공통 목표 ${formatKg(weight)}kg × ${reps}회 · RPE ${rpe} 이하`;
    const lastWeight = Number(previous[previous.length - 1].weight);
    const useLastLungeWeight = ex.name === "덤벨 워킹 런지" && Number.isFinite(lastWeight) && lastWeight > 0;
    const uniform = uniformPerformedSession(previous, Number(ex.baseSets || ex.sets), rpe);
    const performedReps = Math.min(...previous.map(log => parseInt(log.reps) || 0));
    let reason;
    if (!uniform && (!enoughSets || failures.length)) {
        const detail = !enoughSets ? "기본 세트 수 미달" : `${failures.map(log => log.setNo).join(", ")}세트 목표 미달/미완료`;
        reason = useLastLungeWeight
            ? `${detail} → 마지막 실제 중량 ${formatKg(lastWeight)}kg 적용, 목표 ${reps}회 유지`
            : `${detail} → 모든 세트에 이전 공통 목표 유지`;
    } else if (performedReps < minReps) {
        reason = `실제 수행 기준 → 반복 범위 하단 ${minReps}회부터 다시 시작`;
    } else if (performedReps < maxReps) {
        reason = useLastLungeWeight
            ? `모든 세트 성공 → 마지막 실제 중량 ${formatKg(lastWeight)}kg 기준, 목표 1회 증가`
            : "모든 세트 성공 → 모든 세트에서 수행한 중량 기준, 목표 1회 증가";
    } else {
        reason = isAssistedMachineExercise(ex.name)
            ? `최대 반복으로 모든 세트 성공 → 보조중량 감소, ${minReps}회부터 시작`
            : `최대 반복으로 모든 세트 성공 → 중량 증가, ${minReps}회부터 시작`;
    }
    return `${actual}\n${target}\n${reason}`;
}

function openSavedLogEditor(sheetRow) {
    const log = completedLogs.find(item => Number(item.sheetRow) === Number(sheetRow));
    if (!log?.rowVersion) return;
    savedLogEditor = { log: { ...log }, busy: false, request: null, signature: "" };
    document.getElementById("saved-log-title").textContent = `${log.exercise} · ${log.setNo}세트`;
    document.getElementById("saved-log-context").textContent = `${log.date} · ${Number(log.split) === 0 ? "자유운동" : `${log.split}분할 · Week ${log.week} · ${log.day}`}`;
    ["weight", "reps", "rpe"].forEach(key => { document.getElementById(`saved-log-${key}`).value = log[key]; });
    document.getElementById("saved-log-completed").checked = String(log.status).toUpperCase() === "SUCCESS";
    document.getElementById("saved-log-message").textContent = "원래 목표는 유지하며, 수정 전 기록은 보관됩니다.";
    document.getElementById("saved-log-editor").classList.add("active");
}

function closeSavedLogEditor() {
    if (savedLogEditor?.busy) return;
    document.getElementById("saved-log-editor").classList.remove("active");
    savedLogEditor = null;
}

async function saveEditedLog(undo) {
    const editor = savedLogEditor;
    if (!editor || editor.busy) return;
    const values = { undo, rowVersion: editor.log.rowVersion };
    if (!undo) {
        for (const key of ["weight", "reps", "rpe"]) {
            const input = document.getElementById(`saved-log-${key}`);
            if (!input.reportValidity()) return;
            values[key] = Number(input.value);
        }
        values.completed = document.getElementById("saved-log-completed").checked;
    }
    const signature = JSON.stringify(values);
    if (editor.signature !== signature) {
        editor.signature = signature;
        editor.request = { ...values, editId: generateSubmissionId() };
    }
    editor.busy = true;
    const controls = document.querySelectorAll("#saved-log-editor button, #saved-log-editor input");
    controls.forEach(el => { el.disabled = true; });
    const message = document.getElementById("saved-log-message");
    message.textContent = "수정 이력 보관 및 서버 저장 중…";
    try {
        const res = await apiFetch(`/api/workout/logs/${editor.log.sheetRow}/edit`, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(editor.request)
        }, 1);
        if (!res.ok) throw new Error(await readApiError(res));
        const result = await res.json();
        if (!result.saved) throw new Error("저장 결과를 확인하지 못했습니다. 다시 시도해주세요.");
        // Do not replay an already-confirmed edit if refreshing the screen fails.
        editor.busy = false;
        closeSavedLogEditor();
        showWorkoutSaveState("기록 수정 저장 완료", true);
        try {
            const fresh = await apiFetch("/api/workout/bootstrap");
            if (!fresh.ok) throw new Error("기록 새로고침 실패");
            applyBootstrapData(await fresh.json());
            renderCalendar();
            if (selectedCalendarDate) selectCalendarDay(selectedCalendarDate, completedLogs.filter(log => log.date === selectedCalendarDate));
        } catch (_) {
            showWorkoutSaveState("수정은 저장됐습니다 · 화면을 새로고침해주세요");
        }
    } catch (err) {
        message.textContent = err.message || "수정 저장을 확인하지 못했습니다. 다시 시도해주세요.";
    } finally {
        editor.busy = false;
        controls.forEach(el => { el.disabled = false; });
    }
}
