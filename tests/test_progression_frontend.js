const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
const html = fs.readFileSync(path.join(__dirname, '../src/main/resources/static/index.html'), 'utf8');
const names = ['getTargetWeightForExercise', 'normalizeExerciseText', 'isDumbbellExerciseName',
    'isBarbellExerciseName', 'getExerciseIncrementFrontend', 'isAssistedMachineExercise',
    'exerciseWeightMeetsTargetFrontend', 'getProgressedWeightFrontend', 'setSucceededFrontend',
    'logSucceededFrontend', 'parseRepsRangeFrontend', 'clampTargetRepsFrontend',
    'buildReplacementExercise', 'createSetRow', 'handleSetValueChange', 'applyDraftRows'];
const functions = names.map(name => {
    const start = html.indexOf(`        function ${name}(`);
    assert(start >= 0, name);
    const end = html.indexOf('\n        }', start);
    return html.slice(start, end + '\n        }'.length);
}).join('\n');
const gym = { dumbbellInterval: 2.5, availablePlates: [5, 10] };
const definitions = JSON.parse(fs.readFileSync(path.join(__dirname, '../data/exercise_definitions.json'), 'utf8'));
const rows = {};
const inputs = {};
const ctx = {
    exerciseDefinitions: definitions, getActiveGym: () => gym,
    ASSISTED_MACHINE_EXERCISES: new Set(['머신 딥스', '머신 풀업']),
    findExerciseTemplate: (name, ex) => ({ ...ex, name }),
    latestExerciseSessionLogs: () => ctx.logs,
    formatPreviousCell: () => '-', formatIntensityCell: () => '-',
    setSwipeDeleteState: () => {}, bindSetSwipeDelete: () => {},
    oneRms: { activeSplit: 2 }, routineData: {},
    activeWorkoutDay: { exercises: [{ sets: 3 }] },
    calculateVolume: () => {},
    document: {
        createElement: () => ({ dataset: {}, children: [], appendChild(el) { this.children.push(el); } }),
        getElementById: id => rows[id],
        querySelector: selector => inputs[selector],
    },
};
vm.createContext(ctx);
vm.runInContext(functions, ctx);
const ex = { name: '덤벨 슈피네이티드 컬', sets: 3, repsRange: '10-12', rpeTarget: 8 };
ctx.logs = [1, 2, 3].map(setNo => ({ exercise: ex.name, setNo, weight: 9, targetWeight: 9,
    reps: 11, targetReps: 11, rpe: 8, status: 'SUCCESS' }));
let result = ctx.buildReplacementExercise(ex.name, ex);
assert.equal(result.targetWeight, 9);
assert.equal(result.targetReps, 12);
assert.equal(ctx.getTargetWeightForExercise({ targetWeight: 9 }), 9);
ctx.logs[2] = { ...ctx.logs[2], weight: 7.5, reps: 10, rpe: 9, status: 'FAIL' };
result = ctx.buildReplacementExercise(ex.name, ex);
const wrap = ctx.createSetRow(result, 0, 3);
const row = wrap.children[1];
assert.equal(row.dataset.targetWeight, 9);
assert.equal(row.dataset.targetReps, 11);
assert.equal(row.dataset.targetRpe, 8);
assert(row.innerHTML.includes('weight-input" value="7.5"'));
assert(row.innerHTML.includes('reps-input" value="10"'));
assert(row.innerHTML.includes('rpe-input-field" value="9"'));
assert.equal(ctx.setSucceededFrontend({ exercise: ex.name, completed: true,
    weight: 7.5, targetWeight: 9, reps: 11, targetReps: 11, rpe: 8, targetRpe: 8 }), false);
for (const field of ['weight', 'reps']) {
    for (let n = 1; n <= 3; n++) {
        rows[`row-0-${n}`] = { dataset: { targetWeight: 9, targetReps: 11 } };
        inputs[`#row-0-${n} .${field}-input`] = { value: 'old' };
    }
    ctx.handleSetValueChange(0, 1, field, { value: '20' });
    assert.equal(inputs[`#row-0-2 .${field}-input`].value, '20');
    assert.equal(inputs[`#row-0-3 .${field}-input`].value, '20');
    assert.equal(rows['row-0-3'].dataset.targetWeight, 9);
    assert.equal(rows['row-0-3'].dataset.targetReps, 11);
}
assert.equal(ctx.getProgressedWeightFrontend(ex.name, 9), 11.5);
assert.equal(ctx.getProgressedWeightFrontend('플랫 바벨 벤치프레스', 100), 110);
assert.equal(ctx.getProgressedWeightFrontend('머신 풀업', 40), 35);
const copied = ctx.createSetRow(result, 0, 4, { weight: 7.5, reps: 10, rpe: 9,
    targetWeight: 9, targetReps: 11 }).children[1];
assert.equal(copied.dataset.targetWeight, 9);
assert.equal(copied.dataset.targetReps, 11);
assert(copied.innerHTML.includes('weight-input" value="7.5"'));
const draftInputs = { '.weight-input': { value: 40 }, '.reps-input': { value: 11 },
    '.rpe-input-field': { value: 8 } };
rows['row-0-1'] = { dataset: {}, querySelector: selector => draftInputs[selector],
    classList: { toggle() {} } };
ctx.applyDraftRows({ rows: [{ exIdx: 0, rows: [{ setNo: 1, weight: 0, reps: 11,
    rpe: 8, targetWeight: 0, targetReps: 12, targetRpe: 8, checked: true }] }] });
assert.equal(rows['row-0-1'].dataset.targetWeight, 0);
assert.equal(rows['row-0-1'].dataset.targetReps, 12);
assert.equal(draftInputs['.weight-input'].value, 0);
console.log('frontend progression, input rendering and downstream synchronization: PASS');
