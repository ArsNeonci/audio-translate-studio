export const runNumber=(n?:number)=>n?String(n).padStart(6,"0"):"—";
export const percent=(n?:number|null)=>n==null?"—":`${Math.max(0,Math.min(100,n)).toFixed(2)}%`;
export function elapsed(ms?:number|null){if(ms==null)return "—";const s=Math.floor(Math.max(0,ms)/1000);return [Math.floor(s/3600),Math.floor(s/60)%60,s%60].map(n=>String(n).padStart(2,"0")).join(":");}
