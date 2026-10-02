"use client";
import {useCallback,useEffect,useRef,useState} from 'react';

/** Short action feedback only; never use for persisted workflow/license status. */
export function useNotice():[string,(message:string)=>void]{
  const [message,setMessage]=useState('');
  const timer=useRef<ReturnType<typeof setTimeout>|null>(null);
  const notify=useCallback((next:string)=>{
    if(timer.current)clearTimeout(timer.current);
    setMessage(next);
    timer.current=next?setTimeout(()=>{setMessage('');timer.current=null;},3000):null;
  },[]);
  useEffect(()=>()=>{if(timer.current)clearTimeout(timer.current);},[]);
  return [message,notify];
}
