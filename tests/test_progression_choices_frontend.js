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
    'handleSetValueInput','reconcileUnlockedProgressionChoice','toggleProgressionChoice',
    'editProgressionBasis','collectProgressionChoices','nextChoiceTarget']){
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
ex={...ex,name:'덤벨 컬',targetWeight:110,targetReps:10};
edit('weight',100,100,10);
ctx.toggleProgressionChoice(0);
edit('weight',90,90,10);
assert.equal(ex.progressionSelection.mode,'on');
assert.equal(ex.progressionSelection.weight,90);
assert.equal(ex.progressionSelection.originalWeight,110);
assert.equal(painted.basis,'새 기준 90kg × 10회');
edit('reps',6,90,6);
assert.equal(ex.progressionSelection.reps,10);
edit('weight',80,80,6);
assert.equal(ex.progressionSelection.weight,80);
assert.equal(ex.progressionSelection.reps,10);
const updated=JSON.parse(JSON.stringify(ctx.collectProgressionChoices({exercises:[ex]})[ex.name]));
assert.equal(updated.weight,80);
assert.equal(updated.mode,'on');
const updatedLogs=[1,2,3].map(setNo=>({setNo,weight:80,reps:10,rpe:8,completed:true,
    progressionChoice:{...updated,requiredSets:3,rpeTarget:8}}));
assert.equal(ctx.nextChoiceTarget(ex,updatedLogs).weight,80);
assert.equal(ctx.nextChoiceTarget(ex,updatedLogs).reps,11);
ctx.toggleProgressionChoice(0);
edit('weight',70,70,6);
assert.equal(ex.progressionSelection.mode,'off');
assert.equal(ex.progressionSelection.weight,70);
ex.progressionSelection=undefined;
ctx.activeWorkoutMode='free';
edit('weight',40,40,10);
assert.equal(ex.progressionSelection,undefined);
assert(saved>=3);
console.log('choice defaults, manual lock, OFF reversal, draft round-trip, failure baseline, assistance, free exclusion: PASS');

// Weight input must update the persisted ON basis before blur/change fires.
ctx.activeWorkoutMode='routine';
ex={name:'덤벨 컬',sets:3,repsRange:'8-12',rpeTarget:8,targetWeight:110,targetReps:10,
    progressionSelection:{originalWeight:110,originalReps:10,weight:100,reps:10,mode:'on',locked:true}};
const inputRow={querySelector:s=>({value:String(s==='.weight-input'?90:10)})};
ctx.document.getElementById=id=>id==='row-0-1'?inputRow:element;
ctx.handleSetValueInput(0,1,'weight',{value:'90'});
assert(html.includes('oninput="handleSetValueInput(${exIdx}, ${setNo}, \'weight\', this)"'));
assert.equal(ex.progressionSelection.weight,90);
assert.equal(ex.progressionSelection.reps,10);
assert.equal(ex.progressionSelection.mode,'on');

// Deleting the only row that auto-selected a new basis must not advance from it.
ctx.activeWorkoutMode='routine';
ex={name:'curl',sets:4,baseSets:3,repsRange:'8-12',rpeTarget:8,targetWeight:30,targetReps:10};
const rows=[1,2,3,4].map(n=>({id:`row-0-${n}`,dataset:{targetWeight:'30',targetReps:'10'},
    classList:{contains:flag=>flag==='checked'&&n<=3},
    querySelector:s=>({value:String(s==='.weight-input'?(n===4?40:30):(n===4?8:10))})}));
const wrapper=n=>({dataset:{exIdx:'0',setNo:String(n)},remove:()=>rows.splice(n-1,1)});
rows.forEach((row,i)=>{ row.closest=()=>wrapper(i+1); });
ctx.document.getElementById=id=>id==='ex-0'?{querySelectorAll:()=>rows}:id.startsWith('row-0-')?rows[Number(id.split('-').pop())-1]:element;
ctx.document.querySelector=selector=>selector==='#ex-0 .set-row'?rows[0]:null;
Object.assign(ctx,{ensureExerciseBaseSets:()=>3,renumberSetRows:()=>{},updateExerciseMeta:()=>{},
    closeOpenSetSwipeRows:()=>{},calculateVolume:()=>{}});
const deleteStart=html.indexOf('        function deleteSet(');
vm.runInContext(html.slice(deleteStart,html.indexOf('\n        }',deleteStart)+10),ctx);
ctx.recordProgressionEdit(0,'weight',{value:'40'},rows[3]);
ctx.recordProgressionEdit(0,'reps',{value:'8'},rows[3]);
assert.equal(ex.progressionSelection.mode,'on');
ctx.deleteSet(0,4);
const afterDeletion=ctx.collectProgressionChoices({exercises:[ex]})[ex.name];
assert.equal(rows.length,3);
assert.equal(afterDeletion.mode,'unchanged');
assert.equal(afterDeletion.weight,30);
assert.equal(afterDeletion.reps,10);
console.log('removed extra set does not control next target: PASS');
