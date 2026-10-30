const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');
const html = fs.readFileSync(path.join(__dirname, '../src/main/resources/static/index.html'), 'utf8');
const makeRow = (weight, reps, checked) => {
    const inputs = {'.weight-input': {value: weight}, '.reps-input': {value: reps}};
    return {inputs, classList: {contains: name => name === 'checked' && checked},
        querySelector: selector => inputs[selector]};
};
const rows = [makeRow('30', '10', true), makeRow('30', '5', true),
    makeRow('30', '5', true), makeRow('30', '8', false)];
const oldCard = {rows, rpe: '8', extraSets: 1, targetWeight: '35'};
const addCard = {type: 'add'};
const children = [oldCard, addCard];
const container = {
    querySelector: selector => selector === '.free-workout-add-card' ? addCard : null,
    insertBefore: (card, before) => {
        const index = before ? children.indexOf(before) : children.length;
        assert(index >= 0);
        children.splice(index, 0, card);
    }
};
let volumeUpdates = 0, closed = 0, alerts = 0;
const ctx = {recordProgressionEdit: () => {},
    oneRms: {activeSplit: 2}, routineData: {}, currentDayId: 2,
    activeWorkoutMode: 'free', activeWorkoutDay: {exercises: [{name: 'old', sets: 4}]},
    document: {
        getElementById: id => id === 'workout-container' ? container : rows[Number(id.split('-')[2]) - 1]
    },
    calculateVolume: () => volumeUpdates++,
    normalizeFreeWorkoutExercise: name => ({name, sets: 3}),
    createExerciseCard: (ex, index) => ({name: ex.name, index}),
    closeExerciseReplacement: () => closed++,
    alert: () => alerts++,
    renderExercises: () => { throw new Error('Existing cards must not be rebuilt'); }
};
ctx.exerciseAlreadyInSession = name => ctx.activeWorkoutDay.exercises.some(ex => ex.name === name);
vm.createContext(ctx);
for (const name of ['handleSetValueChange', 'addFreeExerciseByName']) {
    const start = html.indexOf(`        function ${name}(`);
    assert(start >= 0);
    vm.runInContext(html.slice(start, html.indexOf('\n        }', start) + 10), ctx);
}
// Correcting an earlier set must preserve completed failures, but still fill future sets.
ctx.handleSetValueChange(0, 1, 'reps', {value: '10'});
assert.deepEqual(rows.map(row => row.inputs['.reps-input'].value), ['10', '5', '5', '10']);
ctx.handleSetValueChange(0, 1, 'weight', {value: '25'});
assert.deepEqual(rows.map(row => row.inputs['.weight-input'].value), ['30', '30', '30', '25']);
assert.equal(volumeUpdates, 2);
// Adding multiple exercises preserves the actual existing nodes, including all entered state.
const before = JSON.stringify(oldCard);
ctx.addFreeExerciseByName('new');
ctx.addFreeExerciseByName('another');
assert.strictEqual(children[0], oldCard);
assert.equal(JSON.stringify(oldCard), before);
assert.deepEqual(children.slice(1, 3), [{name: 'new', index: 1}, {name: 'another', index: 2}]);
assert.strictEqual(children[3], addCard);
assert.equal(closed, 2);
assert.equal(volumeUpdates, 4);
ctx.addFreeExerciseByName('new');
assert.equal(alerts, 1);
assert.equal(children.length, 4);
assert.equal(ctx.activeWorkoutDay.exercises.length, 3);
ctx.activeWorkoutMode = 'routine';
ctx.addFreeExerciseByName('ignored');
assert.equal(children.length, 4);
console.log('completed set edits and free workout input preservation: PASS');
