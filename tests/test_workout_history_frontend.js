const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
const root = path.join(__dirname, '../src/main/resources/static');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const names = ['exerciseSessions','latestExerciseSessionLogs','groupExerciseLogsBySession',
    'groupReplacementLogsByOriginal','getHistoryGroupsForExercise','calculateExerciseRecords',
    'buildHistoryPointFromGroup','buildExerciseHistoryPoints','formatHistoryDateLabel',
    'summarizeSessionLogs','setSucceededFrontend','exerciseWeightMeetsTargetFrontend',
    'isAssistedMachineExercise','normalizeExerciseText','parseRepsRangeFrontend'];
const source = names.map(name => {
    const start=html.indexOf(`        function ${name}(`);
    assert(start>=0,name);
    const end=html.indexOf('\n        }',start);
    return html.slice(start,end+10);
}).join('\n');
const elements = {'workout-save-state':{hidden:true}};
const ctx = {oneRms:{activeSplit:2},activeWorkoutMode:'routine',completedLogs:[],replacementLogs:[],
    ASSISTED_MACHINE_EXERCISES:new Set(['머신 딥스','머신 풀업']),
    formatKg:x=>String(Number(x)),roundToHalf:x=>Math.round(x*2)/2,
    document:{getElementById:id=>elements[id]},setTimeout:()=>1,clearTimeout:()=>{}};
vm.createContext(ctx);
vm.runInContext(source+'\n'+fs.readFileSync(path.join(root,'workout-history.js'),'utf8'),ctx);
const make=(exercise,day,weight,reps=12)=>[1,2,3].map(setNo=>({date:'2026-10-01',split:2,week:1,
    exercise,day,setNo,weight,reps,targetWeight:weight,targetReps:reps,rpe:8,status:'SUCCESS'}));
ctx.completedLogs=[...make('레그 컬','Day 1',30),...make('레그 컬','Day 3',50,8),
    ...make('싱글 레그 레그 컬','Day 1',15),...make('레그 컬','Day 1',35)];
assert.equal(ctx.buildExerciseHistoryPoints('레그 컬','Day 1').length,2);
assert.deepEqual(Array.from(ctx.buildExerciseHistoryPoints('레그 컬','Day 1'),p=>p.weight),[30,35]);
assert.equal(ctx.buildExerciseHistoryPoints('레그 컬','Day 3')[0].weight,50);
assert.equal(ctx.calculateExerciseRecords('레그 컬','Day 1').bestWeight,'35kg');
assert.equal(ctx.calculateExerciseRecords('싱글 레그 레그 컬','Day 1').bestWeight,'15kg');
const ex={name:'힙 어브덕션',sets:3,repsRange:'12-15',rpeTarget:8};
ctx.completedLogs=make(ex.name,'Day 3',97.5);
assert(ctx.describeProgression(ex,'Day 3').includes('목표 1회 증가'));
ctx.completedLogs[2].reps=5;
assert(ctx.describeProgression(ex,'Day 3').includes('3세트 목표 미달'));
assert(ctx.describeProgression(ex,'Day 1').includes('이전 기록 없음'));
ctx.completedLogs=make('머신 풀업','Day 3',40,12);
assert(ctx.describeProgression({...ex,name:'머신 풀업',repsRange:'8-12'},'Day 3').includes('보조중량 감소'));
ctx.showWorkoutSaveState('기기에 보관됨 · 서버 저장 중');
assert.equal(elements['workout-save-state'].hidden,false);
assert(elements['workout-save-state'].textContent.includes('기기에 보관됨'));
ctx.showWorkoutSaveState('서버 저장 완료',true);
assert.equal(elements['workout-save-state'].textContent,'서버 저장 완료');
console.log('A/B and exact name graph isolation, repeated sessions, progression explanation, save state: PASS');
