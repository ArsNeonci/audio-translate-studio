import type { Job } from "@/lib/jobs";
import { pythonCommand } from "@/lib/rules";
export type Scope = "workflows" | "tools";
export type HistoryFile = {id:string;step:string;type:string;path:string;size:number;created_at:string;status:"AVAILABLE"|"STALE"|"PUBLISHING"};
export type HistoryJob = Omit<Job,"status"> & {status:string;files:HistoryFile[];storage_scope:Scope;tool_type?:string;input_file?:string};
const shared = globalThis as typeof globalThis & {audioHistoryMigration?:Promise<void>};
export async function ensureHistory(){
  if(!shared.audioHistoryMigration)shared.audioHistoryMigration=pythonCommand<{status:number;error?:string}>("manage.py",{action:"initialize"}).then(r=>{if(r.status!==200)throw new Error(r.error||"Cannot migrate storage");}).catch(e=>{shared.audioHistoryMigration=undefined;throw e;});
  await shared.audioHistoryMigration;
}
export async function historyList(params:URLSearchParams,scope:Scope="workflows"){
  await ensureHistory();
  const result=await pythonCommand<{status:number;jobs:HistoryJob[];error?:string}>("manage.py",{action:"history",scope});
  if(result.status!==200)throw new Error(result.error);
  const jobs=result.jobs,statuses=[...new Set(jobs.map(j=>j.status))].sort();
  const search=(params.get("search")||"").toLocaleLowerCase(),status=params.get("status");
  const filtered=jobs.filter(j=>(!status||status==="ALL"||j.status===status)&&`${j.workflow_no} ${j.id} ${j.name} ${j.url}`.toLocaleLowerCase().includes(search));
  const order=params.get("sort")==="oldest"?1:-1;
  filtered.sort((a,b)=>order*a.created_at.localeCompare(b.created_at));
  const limit=Math.max(1,Math.min(100,Number(params.get("limit"))||25)),page=Math.max(1,Math.floor(Number(params.get("page"))||1));
  return {jobs:filtered.slice((page-1)*limit,page*limit),total:filtered.length,page,limit,statuses};
}
export async function getHistoryJob(id:string,scope:Scope="workflows"):Promise<HistoryJob|null>{
  if(!/^[0-9a-f-]{36}$/.test(id))return null;
  await ensureHistory();
  const result=await pythonCommand<{status:number;jobs:HistoryJob[]}>("manage.py",{action:"history",scope});
  return result.jobs?.find(j=>j.id===id)||null;
}
export async function resolveHistoryFile(id:string,fileId:string,scope:Scope="workflows"){
  if(!/^[0-9a-f-]{36}$/.test(id))return null;
  await ensureHistory();
  const result=await pythonCommand<{status:number;resolved?:{item:HistoryFile;file:string}}>("manage.py",{action:"resolve",id,file:fileId,scope});
  return result.resolved||null;
}
