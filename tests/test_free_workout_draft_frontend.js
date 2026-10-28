const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert');
const html = fs.readFileSync(path.join(__dirname, '../src/main/resources/static/index.html'), 'utf8');
const elements = {};
const el = id => elements[id] ||= {style: {}, classList: {add() {}, remove() {}}};
let savedRows;
const ctx = {
    console, Date, oneRms: {activeSplit: 2}, routineData: {},
    activeWorkoutDay: null, activeWorkoutMode: 'routine', activeWorkoutDraftDisabled: false,
    activeWorkoutDraftId: null, activeWorkoutDraftCreatedAt: null, activeWorkoutSubmissionId: null,
    isFinishingWorkout: false, isRestoringWorkoutDraft: false, authUser: {username: 'test'},
    currentDayId: null, stopwatchInterval: 1, stopwatchPaused: false,
    ACTIVE_WORKOUT_DRAFT_ID: 'draft', DraftManager: {hasDraftSignal: () => false},
    document: {getElementById: el, querySelectorAll: () => []},
    generateDraftId: () => 'draft-id', getLocalDateString: () => '2026-10-28',
    getActiveWeekNum: () => 3, getActiveProgramDayNum: () => 2,
    getCurrentStopwatchElapsedMs: () => 123000,
    collectActiveWorkoutRows: () => [{exIdx: 0, rows: [{setNo: 1, checked: true, weight: '25',
        reps: '10', rpe: '8', targetWeight: '30', targetReps: '12'}]}],
    setActiveWorkoutMode: mode => ctx.activeWorkoutMode = mode,
    openActiveWorkoutView() {}, renderExercises: day => {ctx.rendered = day;},
    stopRestTimer() {}, startStopwatch() {}, startWorkoutKeepAlive() {}, calculateVolume() {},
    setActiveWorkoutHeaderVisible() {}, setActiveSplitSegmentUI() {}, resetWorkoutScroll() {},
    applyDraftRows: draft => {savedRows = draft.rows;},
    restoreStopwatchFromDraft: draft => {ctx.restoredElapsed = draft.stopwatch.elapsedMs;},
    scheduleActiveWorkoutHeaderSpaceUpdate() {}, saveActiveWorkoutDraftNow: async () => {},
    getProgramWorkoutTitle: () => 'Routine', alert: () => {throw Error('Unexpected routine dependency');}
};
vm.createContext(ctx);
for (const name of ['startFreeWorkout', 'collectActiveWorkoutDraft', 'restoreActiveWorkoutDraft', 'normalizeDraft']) {
    const indent = name === 'normalizeDraft' ? '            ' : '        ';
    const asyncPrefix = name === 'restoreActiveWorkoutDraft' ? 'async ' : '';
    const start = html.indexOf(`${indent}${asyncPrefix}function ${name}(`);
    assert(start >= 0);
    vm.runInContext(html.slice(start, html.indexOf(`\n${indent}}`, start) + indent.length + 2), ctx);
}
(async () => {
    ctx.startFreeWorkout();
    assert.equal(ctx.activeWorkoutDraftDisabled, false);
    ctx.activeWorkoutDay.exercises.push({name: '레그 컬', sets: 4, baseSets: 3, restSeconds: 30});
    ctx.activeWorkoutSubmissionId = 'same-submission';
    const draft = ctx.normalizeDraft(JSON.parse(JSON.stringify(ctx.collectActiveWorkoutDraft())));
    assert.equal(draft.mode, 'free');
    assert.equal(draft.rows[0].rows[0].checked, true);
    ctx.activeWorkoutMode = 'routine';
    ctx.activeWorkoutDay = null;
    ctx.oneRms.activeSplit = 5; // Restoring free workout must not change regular split.
    await ctx.restoreActiveWorkoutDraft(draft);
    assert.equal(ctx.activeWorkoutMode, 'free');
    assert.equal(ctx.oneRms.activeSplit, 5);
    assert.equal(ctx.activeWorkoutSubmissionId, 'same-submission');
    assert.equal(ctx.activeWorkoutDay.exercises[0].sets, 4);
    assert.equal(ctx.activeWorkoutDay.exercises[0].restSeconds, 30);
    assert.equal(ctx.restoredElapsed, 123000);
    assert.deepEqual(savedRows, draft.rows);
    assert.equal(el('active-day-title').innerText, '자유운동');
    assert.equal(ctx.normalizeDraft({...draft, mode: undefined}).mode, 'free');
    const routine = {...draft, mode: undefined, dayId: 'Day 2', split: 2};
    assert.equal(ctx.normalizeDraft(routine).mode, 'routine');
    ctx.routineData = {'2': []};
    await ctx.restoreActiveWorkoutDraft(routine);
    assert.equal(ctx.activeWorkoutMode, 'routine');
    assert.equal(ctx.oneRms.activeSplit, 2);
    console.log('free workout draft round-trip, mode, sets, timer, submission and legacy routine: PASS');
})().catch(error => {console.error(error); process.exitCode = 1;});
