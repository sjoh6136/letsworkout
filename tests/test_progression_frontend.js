const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
const html = fs.readFileSync(path.join(__dirname, '../src/main/resources/static/index.html'), 'utf8');
const names = ['nextChoiceTarget', 'isBodyweightExercise', 'uniformPerformedSession', 'getTargetWeightForExercise', 'normalizeExerciseText', 'isDumbbellExerciseName',
    'isBarbellExerciseName', 'getExerciseIncrementFrontend', 'isAssistedMachineExercise',
    'exerciseWeightMeetsTargetFrontend', 'getProgressedWeightFrontend', 'setSucceededFrontend',
    'logSucceededFrontend', 'parseRepsRangeFrontend', 'clampTargetRepsFrontend',
    'roundToStep', 'resolveEquipmentWeightFrontend', 'buildReplacementExercise', 'createSetRow', 'handleSetValueChange', 'applyDraftRows'];
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
    oneRms: { activeSplit: 2 }, routineData: {}, currentDayId: "Day 3", activeWorkoutMode: "routine",
    activeWorkoutDay: { exercises: [{ sets: 3 }] },
    calculateVolume: () => {}, recordProgressionEdit: () => {},
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
assert(row.innerHTML.includes('weight-input" value="9"'));
assert(row.innerHTML.includes('reps-input" value="11"'));
assert(row.innerHTML.includes('rpe-input-field" value="8"'));
assert.equal(ctx.setSucceededFrontend({ exercise: ex.name, completed: true,
    weight: 7.5, targetWeight: 9, reps: 11, targetReps: 11, rpe: 8, targetRpe: 8 }), false);
for (const field of ['weight', 'reps']) {
    for (let n = 1; n <= 3; n++) {
        rows[`row-0-${n}`] = {
            dataset: { targetWeight: 9, targetReps: 11 },
            classList: { contains: () => false },
            querySelector: selector => inputs[`#row-0-${n} ${selector}`]
        };
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
const fly = { name: '케이블 플라이', sets: 3, repsRange: '12-15', rpeTarget: 8 };
ctx.logs = [13, 11, 11].map((reps, index) => ({ exercise: fly.name, setNo: index + 1,
    weight: 20.1, targetWeight: 20.1, reps, targetReps: reps, rpe: 8, status: 'SUCCESS' }));
result = ctx.buildReplacementExercise(fly.name, fly);
assert.deepEqual(Array.from(result.progressionSets, s => s.reps), [13, 13, 13]);
assert.deepEqual(Array.from(result.progressionSets, s => s.targetReps), [13, 13, 13]);
for (let setNo = 1; setNo <= 3; setNo++) {
    const flyRow = ctx.createSetRow(result, 0, setNo).children[1];
    assert(flyRow.innerHTML.includes('reps-input" value="13"'));
}
const ohp = { name: '오버헤드 프레스 (OHP - 바벨)', sets: 3, repsRange: '10-12', rpeTarget: 7 };
ctx.logs = [10, 9, 8].map((reps, index) => ({ exercise: ohp.name, setNo: index + 1,
    weight: 30, targetWeight: 30, reps, targetReps: reps, rpe: 7, status: 'SUCCESS' }));
result = ctx.buildReplacementExercise(ohp.name, ohp);
assert.deepEqual(Array.from(result.progressionSets, s => s.reps), [10, 10, 10]);
const unevenOHP = { ...ohp, repsRange: '6-8', rpeTarget: 8 };
ctx.logs = [8, 5, 5].map((reps, index) => ({ exercise: unevenOHP.name, setNo: index + 1,
    weight: 30, targetWeight: 30, reps, targetReps: reps, rpe: 8, status: 'SUCCESS' }));
result = ctx.buildReplacementExercise(unevenOHP.name, unevenOHP);
assert.deepEqual(Array.from(result.progressionSets, s => s.reps), [8, 8, 8]);
console.log('frontend progression, input rendering and downstream synchronization: PASS');

for (const [name, weights, targetWeight, repsRange, reps, expectedWeight, incrementedWeight, minReps, maxReps] of [
    ['힙 어브덕션', [100, 97.5, 97.5], 38.5, '12-15', 12, 97.5, 100, 12, 15],
    ['머신 풀업', [25, 30, 30], 40, '8-10', 9, 30, 25, 8, 10],
]) {
    const exercise = { name, sets: 3, repsRange, rpeTarget: 8 };
    ctx.logs = weights.map((weight, i) => ({ exercise: name, setNo: i + 1,
        weight, targetWeight, reps, targetReps: reps, rpe: 8, status: 'SUCCESS' }));
    let progressed = ctx.buildReplacementExercise(name, exercise);
    assert.deepEqual(Array.from(progressed.progressionSets, s => [s.weight, s.reps]),
        [[expectedWeight, reps + 1], [expectedWeight, reps + 1], [expectedWeight, reps + 1]]);
    ctx.logs.forEach(log => { log.reps = maxReps; log.targetReps = maxReps; });
    progressed = ctx.buildReplacementExercise(name, exercise);
    assert.equal(progressed.targetWeight, incrementedWeight);
    assert.equal(progressed.targetReps, minReps);
    ctx.logs[2].status = 'FAIL';
    progressed = ctx.buildReplacementExercise(name, exercise);
    assert.equal(progressed.targetWeight, targetWeight);
    assert.equal(progressed.targetReps, maxReps);
}
console.log('successful performed weights and failed target retries: PASS');

const lunge = {name:'덤벨 워킹 런지',sets:3,repsRange:'10-12',rpeTarget:8};
gym.dumbbellInterval = 2;
ctx.logs = [10,8,7].map((reps,i)=>({exercise:lunge.name,setNo:i+1,
    weight:i===0?27.5:25,targetWeight:26,reps,targetReps:10,rpe:8,status:'FAIL'}));
result = ctx.buildReplacementExercise(lunge.name,lunge);
assert.deepEqual(Array.from(result.progressionSets,s=>[s.weight,s.reps]),[[25,10],[25,10],[25,10]]);
const lungeRow = ctx.createSetRow(result,0,1).children[1];
assert.equal(lungeRow.dataset.targetWeight,25);
assert(lungeRow.innerHTML.includes('weight-input" value="25"'));
ctx.logs.forEach((log,i)=>Object.assign(log,{weight:i===2?27.5:25,targetWeight:25,reps:10,status:'SUCCESS'}));
result = ctx.buildReplacementExercise(lunge.name,lunge);
assert.equal(result.targetWeight,27.5);
assert.equal(result.targetReps,11);
ctx.logs.forEach(log=>Object.assign(log,{reps:12,targetReps:12}));
result = ctx.buildReplacementExercise(lunge.name,lunge);
assert.equal(result.targetWeight,33.5);
assert.equal(result.targetReps,10);
for (const weight of [0,-1,NaN]) {
    Object.assign(ctx.logs[2],{weight,status:'FAIL'});
    result = ctx.buildReplacementExercise(lunge.name,lunge);
    assert.equal(result.targetWeight,25);
    assert.equal(result.targetReps,12);
}
const lyingCurl={name:'싱글 레그 라잉 레그 컬',sets:3,repsRange:'12-15',rpeTarget:8};
ctx.logs=[1,2,3].map(setNo=>({exercise:lyingCurl.name,setNo,weight:20,targetWeight:22.7,
    reps:15,targetReps:13,rpe:8,status:'FAIL'}));
result=ctx.buildReplacementExercise(lyingCurl.name,lyingCurl);
assert.equal(result.targetWeight,22.5);
assert.equal(result.targetReps,12);
gym.dumbbellInterval = 2.5;
console.log('walking lunge last weight and adjusted lying leg curl: PASS');

const pull = {name:'리버스 그립 랫 풀다운',sets:3,repsRange:'6-8',rpeTarget:8};
for (const [weight,reps,nextWeight,nextReps] of [[60,6,60,7],[65,5,65,6],[60,8,65,6]]) {
    ctx.logs=[1,2,3].map(setNo=>({setNo,weight,reps,targetWeight:65,targetReps:7,rpe:8,status:'FAIL'}));
    result=ctx.buildReplacementExercise(pull.name,pull);
    assert.equal(result.targetWeight,nextWeight);
    assert.equal(result.targetReps,nextReps);
}
ctx.logs=[1,2,3].map(setNo=>({setNo,weight:20,reps:12,targetWeight:20,targetReps:14,rpe:8,status:'FAIL'}));
assert.equal(ctx.buildReplacementExercise(fly.name,fly).targetReps,13);
ctx.logs.forEach(log=>Object.assign(log,{reps:10,targetReps:10}));
assert.equal(ctx.buildReplacementExercise(fly.name,fly).targetReps,12);
ctx.logs.forEach(log=>Object.assign(log,{rpe:9,targetReps:20}));
assert.equal(ctx.buildReplacementExercise(fly.name,fly).targetReps,15);
for (const change of [{completed:false},{checked:false},{rpe:0},{rpe:9}]) {
    ctx.logs=[1,2,3].map(setNo=>({setNo,weight:60,reps:6,targetWeight:65,targetReps:7,rpe:8,status:'FAIL'}));
    Object.assign(ctx.logs[2],change);
    result=ctx.buildReplacementExercise(pull.name,pull);
    assert.equal(result.targetWeight,65);
    assert.equal(result.targetReps,7);
}
console.log('actual working load, one-rep progression, range boundaries, completion and RPE: PASS');

const staleRange = {...fly,targetReps:10,progressionSets:[{setNo:1,reps:10,targetReps:10,weight:20,targetWeight:20}]};
const boundedRow = ctx.createSetRow(staleRange,0,1).children[1];
assert.equal(boundedRow.dataset.targetReps,12);
assert(boundedRow.innerHTML.includes('reps-input" value="12"'));
const actualRow = ctx.createSetRow(staleRange,0,1,{reps:10}).children[1];
assert(actualRow.innerHTML.includes('reps-input" value="10"'));

for (const name of [pull.name,'머신 풀업','머신 딥스']) {
    const assisted=name!==pull.name;
    ctx.logs=[1,2,3].map(setNo=>({exercise:name,setNo,weight:0,reps:8,targetWeight:65,targetReps:8,rpe:8,status:'FAIL',completed:true}));
    const target=ctx.buildReplacementExercise(name,{...pull,name});
    assert.equal(target.targetWeight,assisted?0:65);
    assert.equal(target.targetReps,assisted?6:8);
}
ctx.logs=[1,2,3].map(setNo=>({exercise:pull.name,setNo,weight:65,reps:6,targetWeight:65,targetReps:6,rpe:8,status:'SUCCESS'}));
Object.assign(ctx.logs[2],{rpe:0,status:'FAIL'});
assert.equal(ctx.buildReplacementExercise(pull.name,pull).targetReps,6);

// Exercise isolation tests use the real lookup functions, replacing the earlier stubs.
for (const name of ['findExerciseTemplate', 'exerciseSessions', 'latestExerciseSessionLogs',
                    'exerciseAlreadyInSession', 'groupExerciseLogsBySession']) {
    const start = html.indexOf(`        function ${name}(`);
    const end = html.indexOf('\n        }', start);
    vm.runInContext(html.slice(start, end + '\n        }'.length), ctx);
}
ctx.getActiveWorkoutDayObj = () => ctx.activeWorkoutDay;
ctx.routineData = JSON.parse(fs.readFileSync(path.join(__dirname, '../data/routines.json'), 'utf8'));
ctx.currentDayId = 'Day 3';
const hip = ctx.findExerciseTemplate('힙 어브덕션');
assert.equal(hip.repsRange, '12-15');
assert.equal(hip.rpeTarget, 9);
ctx.logs = undefined;
ctx.completedLogs = [
    {exercise:'힙 어브덕션',split:2,day:'Day 3',date:'2026-10-01',week:1,setNo:1,weight:97.5},
    {exercise:'힙 어브덕션',split:2,day:'Day 1',date:'2026-10-06',week:2,setNo:1,weight:40}
];
assert.equal(ctx.latestExerciseSessionLogs('힙 어브덕션', 'Day 3')[0].weight, 97.5);
for (const [regular, single] of [['레그 익스텐션','싱글 레그 레그 익스텐션'],['레그 컬','싱글 레그 라잉 레그 컬']]) {
    ctx.completedLogs = [[regular,40,15],[single,15,12]].flatMap(([exercise,weight,reps]) =>
        [1,2,3].map(setNo => ({exercise,weight,reps,setNo,split:2,day:'Day 3',date:'2026-10-06',
            week:1,targetWeight:weight,targetReps:reps,rpe:8,status:'SUCCESS'})));
    assert.equal(ctx.latestExerciseSessionLogs(regular, 'Day 3')[0].weight, 40);
    assert.equal(ctx.latestExerciseSessionLogs(single, 'Day 3')[0].weight, 15);
    const target = ctx.buildReplacementExercise(single, {sets:3,repsRange:'12-15',rpeTarget:8});
    assert.equal(target.targetWeight, 15);
    assert.equal(target.targetReps, 13);
}
const log = {exercise:'힙 어브덕션',split:2,day:'Day 3',date:'2026-10-06',week:1,
    weight:97.5,targetWeight:97.5,reps:12,targetReps:12,rpe:8};
for (const useIds of [true, false]) {
    ctx.completedLogs = ['FAIL','SUCCESS'].flatMap((status, i) => [1,2,3].map(setNo =>
        ({...log,status,setNo,submissionId:useIds ? `session-${i}` : ''})));
    assert.equal(ctx.latestExerciseSessionLogs(log.exercise,'Day 3').length,3);
    assert.equal(ctx.latestExerciseSessionLogs(log.exercise,'Day 3')[0].status,'SUCCESS');
    assert.equal(ctx.groupExerciseLogsBySession(log.exercise).length,2);
    assert.equal(ctx.buildReplacementExercise(log.exercise,hip).targetReps,13);
}
ctx.completedLogs = [];
const replacement = ctx.buildReplacementExercise('머신 로우', {name:'바벨 로우',targetWeight:100,sets:3,repsRange:'8-10',rpeTarget:8});
assert.equal(replacement.targetWeight,0);
assert.equal(replacement.repsRange,'8-10');
ctx.activeWorkoutDay={exercises:[{name:'레그 컬'},{name:'싱글 레그 라잉 레그 컬'}]};
assert.equal(ctx.exerciseAlreadyInSession('레그 컬',1),true);
assert.equal(ctx.exerciseAlreadyInSession('레그 컬',0),false);
assert.equal(ctx.exerciseAlreadyInSession('레그 익스텐션'),false);
console.log('day, exercise, session isolation and duplicate prevention: PASS');

for (const name of ['replaceExerciseWithName', 'addFreeExerciseByName', 'getWorkoutSessionsFromLogs']) {
    const start = html.indexOf(`        function ${name}(`);
    vm.runInContext(html.slice(start, html.indexOf('\n        }',start) + '\n        }'.length),ctx);
}
let alerts = 0;
ctx.alert = () => { alerts++; };
ctx.replacementExerciseIdx = 1;
ctx.replaceExerciseWithName('레그 컬');
assert.equal(alerts,1);
assert.equal(ctx.activeWorkoutDay.exercises[1].name,'싱글 레그 라잉 레그 컬');
ctx.activeWorkoutMode = 'free';
ctx.addFreeExerciseByName('레그 컬');
assert.equal(alerts,2);
assert.equal(ctx.activeWorkoutDay.exercises.length,2);
const repeated = ['FAIL','SUCCESS'].flatMap(status => [1,2,3].map(setNo => ({...log,status,setNo})));
assert.equal(ctx.getWorkoutSessionsFromLogs(repeated).length,2);
console.log('duplicate action guards and repeated session progress: PASS');

gym.dumbbellInterval = 2;
gym.availablePlates = [2.5, 5];
assert.equal(ctx.isBarbellExerciseName('고블릿 스쿼트'), false);
assert.equal(ctx.resolveEquipmentWeightFrontend('고블릿 스쿼트', 8), 8);
assert.equal(ctx.resolveEquipmentWeightFrontend('고블릿 스쿼트', 24), 24);
assert.equal(ctx.getProgressedWeightFrontend('고블릿 스쿼트', 20), 26);
gym.dumbbellInterval = 2.5;
assert.equal(ctx.resolveEquipmentWeightFrontend('해머 컬', 12), 12.5);
for (const name of ['EZ바 컬', 'EZ바 스컬크러셔']) {
    assert.equal(ctx.getProgressedWeightFrontend(name, 20), 25);
    assert.equal(ctx.resolveEquipmentWeightFrontend(name, 10), 10);
}
ctx.activeWorkoutMode = 'routine';
for (const name of ['체중 풀업', '체중 딥스', '친업']) {
    const bodyEx = {name, sets: 3, repsRange: '8-12', rpeTarget: 8};
    ctx.logs = [1, 2, 3].map(setNo => ({exercise: name, setNo, weight: 0, targetWeight: 0,
        reps: 10, targetReps: 10, rpe: 8, status: 'SUCCESS', completed: true}));
    assert(ctx.setSucceededFrontend({...ctx.logs[0], targetRpe: 8}));
    // Restore the test's session lookup stub, replaced by other test sections.
    ctx.latestExerciseSessionLogs = () => ctx.logs;
    let next = ctx.buildReplacementExercise(name, bodyEx);
    assert.equal(next.targetWeight, 0);
    assert.equal(next.targetReps, 11);
    ctx.logs.forEach(log => { log.reps = 12; log.targetReps = 12; });
    next = ctx.buildReplacementExercise(name, bodyEx);
    assert.equal(next.targetWeight, 5);
    assert.equal(next.targetReps, 8);
    ctx.logs[2].rpe = 0;
    ctx.logs[2].status = 'FAIL';
    ctx.logs[2].completed = false;
    next = ctx.buildReplacementExercise(name, bodyEx);
    assert.equal(next.targetWeight, 0);
    assert.equal(next.targetReps, 12);
    assert.equal(ctx.exerciseWeightMeetsTargetFrontend(name, -1, 0), false);
}
console.log('named equipment steps and bodyweight zero-load progression: PASS');
