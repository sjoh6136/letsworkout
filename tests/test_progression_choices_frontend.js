const fs = require('fs'), vm = require('vm'), assert = require('assert');
const html = fs.readFileSync(require('path').join(__dirname,'../src/main/resources/static/index.html'),'utf8');
let ex = {name:'덤벨 컬',sets:3,repsRange:'8-12',rpeTarget:8,targetWeight:15,targetReps:8};
let painted = {}, saved = 0;
const element = {hidden:true,querySelector: selector => selector === '.progression-switch'
    ? {setAttribute:(key,value)=>painted[key]=value} : {set textContent(value){painted.basis=value;}}};
const ctx = {console, activeWorkoutMode:'routine', getActiveWorkoutDayObj:()=>({exercises:[ex]}),
    document:{getElementById:()=>element}, getTargetWeightForExercise:ex=>ex.targetWeight,
    parseRepsRangeFrontend:()=>[8,12],clampTargetRepsFrontend:(n,lo,hi)=>Math.min(hi,Math.max(lo,n)),
    formatKg:String,scheduleActiveWorkoutDraftSave:()=>saved++,isAssistedMachineExercise:n=>n==='머신 풀업',
    exerciseWeightMeetsTargetFrontend:(n,w,t)=>n==='머신 풀업'?w<=t:w>=t,
    getProgressedWeightFrontend:(n,w)=>n==='머신 풀업'?Math.max(0,w-5):w+2.5};
vm.createContext(ctx);
for(const name of ['originalProgressionBasis','paintProgressionChoice','recordProgressionEdit',
    'toggleProgressionChoice','editProgressionBasis','collectProgressionChoices','nextChoiceTarget']){
    const start=html.indexOf(`        function ${name}(`);
    assert(start>=0,name);
    vm.runInContext(html.slice(start,html.indexOf('\n        }',start)+10),ctx);
}
const edit=(field,value,weight,reps)=>ctx.recordProgressionEdit(0,field,{value:String(value)},
    {querySelector:s=>({value:String(s==='.weight-input'?weight:reps)})});
edit('weight',8,8,8);
assert.equal(ex.progressionSelection.mode,'off');
assert.equal(element.hidden,false);
edit('reps',11,8,11);
ctx.toggleProgressionChoice(0);
assert.equal(ex.progressionSelection.mode,'on');
assert.equal(painted.basis,'새 기준 8kg × 11회');
edit('reps',6,8,6);
assert.equal(ex.progressionSelection.reps,11); // Actual failures cannot overwrite the baseline.
ctx.toggleProgressionChoice(0);
assert.equal(ex.progressionSelection.mode,'off');
const persisted=JSON.parse(JSON.stringify(ex));
ex=persisted;
assert.equal(ctx.collectProgressionChoices({exercises:[ex]})['덤벨 컬'].mode,'off');
ctx.toggleProgressionChoice(0);
assert.equal(ex.progressionSelection.originalWeight,15);
const choice={...ex.progressionSelection,requiredSets:3,rpeTarget:8};
let logs=[1,2,3].map(setNo=>({setNo,weight:8,reps:11,rpe:8,completed:true,progressionChoice:choice}));
assert.equal(ctx.nextChoiceTarget(ex,logs).reps,12);
logs[2].reps=6;
assert.equal(ctx.nextChoiceTarget(ex,logs).reps,11);
logs[2].reps=11; logs[2].rpe=9;
assert.equal(ctx.nextChoiceTarget(ex,logs).reps,11);
ex={...ex,progressionSelection:undefined,targetWeight:30,targetReps:10};
edit('weight',40,40,10);edit('reps',8,40,8);
assert.equal(ex.progressionSelection.mode,'on');
assert.equal(ex.progressionSelection.reps,8);
ex={...ex,progressionSelection:undefined,name:'머신 풀업'};
edit('weight',20,20,10);
assert.equal(ex.progressionSelection.mode,'on');
edit('weight',40,40,10);
assert.equal(ex.progressionSelection.mode,'off');
edit('weight',30,30,10);
assert.equal(ex.progressionSelection,undefined);
assert.equal(element.hidden,true);
ctx.activeWorkoutMode='free';
edit('weight',40,40,10);
assert.equal(ex.progressionSelection,undefined);
assert(saved>=3);
console.log('choice defaults, manual lock, OFF reversal, draft round-trip, failure baseline, assistance, free exclusion: PASS');
