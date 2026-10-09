import {sameLiveJob,mergeReferenceSnapshots,reconcileLiveJobs} from './live-history.js?v=88.0';

const copy=value=>structuredClone(value);
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);

// A tab owns only fields changed since its own last read/successful save.
function changedFields(stored,local,baseline,skip=[]){
 const result={...(stored||{})};
 for(const key of new Set([...Object.keys(local||{}),...Object.keys(baseline||{})])){
  if(skip.includes(key)||same(local?.[key],baseline?.[key]))continue;
  if(Object.hasOwn(local||{},key))result[key]=copy(local[key]);else delete result[key];
 }
 return result;
}
const sameJob=sameLiveJob;
function mergeDraft(stored,local,baseline){
 const maps=['catalogValues','catalogTexts','catalogSeedModes','catalogApis','catalogUi','liveSettings','advanced'];
 const result=changedFields(stored,local,baseline,maps);
 for(const key of maps){
  if(same(local?.[key],baseline?.[key]))continue;
  if(!Object.hasOwn(local||{},key)){delete result[key];continue;}
  const value=local[key];result[key]=value&&typeof value==='object'&&!Array.isArray(value)?changedFields(stored?.[key],value,baseline?.[key]):copy(value);
 }
 return result;
}
function mergeOutputs(stored=[],local=[],baseline=[]){
 const result=copy(stored);
 for(const output of local){const index=result.findIndex(o=>o.id===output.id),old=baseline.find(o=>o.id===output.id);if(index<0)result.push(copy(output));else result[index]=changedFields(result[index],output,old);}
 return result;
}
function mergeJobs(stored=[],local=[],baseline=[]){
 const result=copy(stored),terminal=new Set(['done','failed','cancelled','abandoned']);
 for(const job of local){
  const index=result.findIndex(j=>sameJob(j,job)),old=baseline.find(j=>sameJob(j,job));
  if(index<0){result.push(copy(job));continue;}
  const current=result[index],merged=changedFields(current,job,old,['outputs','id']);
  if(!old&&current.snapshot)merged.snapshot=copy(current.snapshot);
  if(merged.snapshot&&job.snapshot?.refs?.length)merged.snapshot.refs=mergeReferenceSnapshots(job.snapshot.refs,merged.snapshot.refs?.length?merged.snapshot.refs:job.snapshot.refs);
  merged.id=current.id;merged.outputs=mergeOutputs(current.outputs,job.outputs,old?.outputs);
  // A stale poll cannot resurrect an already finished attempt.
  if(terminal.has(current.status)&&!terminal.has(job.status)&&Number(job.started||0)<=Number(current.started||0))for(const key of ['status','serverStatus','stage','ended','error','connection_error','progress']){if(Object.hasOwn(current,key))merged[key]=copy(current[key]);else delete merged[key];}
  result[index]=merged;
 }
 return result;
}

export function mergeWorkspaceSnapshots(stored,local,baseline){
 if(!stored)return copy(local);
 const result=changedFields(stored,local,baseline,['sessions','nextSession','nextJob']);
 result.sessions=copy(stored.sessions||[]);
 for(const session of local.sessions||[]){
  const index=result.sessions.findIndex(s=>s.id===session.id),old=baseline?.sessions?.find(s=>s.id===session.id);
  if(index<0){result.sessions.push(copy(session));continue;}
  const current=result.sessions[index],merged=changedFields(current,session,old,['jobs','draft']);
  merged.draft=mergeDraft(current.draft,session.draft,old?.draft);
  merged.jobs=mergeJobs(current.jobs,session.jobs,old?.jobs);result.sessions[index]=merged;
 }
 // Old short IDs/routes remain valid; new records use UUIDs rather than counters.
 for(const key of ['nextSession','nextJob'])result[key]=Math.max(Number(stored[key])||1,Number(local[key])||1);
 reconcileLiveJobs(result.sessions);
 return result;
}
