"use client";
import {useCallback,useEffect,useRef,useState} from 'react';
import { useLanguage } from '@/lib/i18n/language-context';

/** Short action feedback only; never use for persisted workflow/license status. */
export function useNotice():[string,(message:string)=>void]{
  const { tr } = useLanguage();
  const [message,setMessage]=useState('');
  const timer=useRef<ReturnType<typeof setTimeout>|null>(null);
  const notify=useCallback((next:string)=>{
    if(timer.current)clearTimeout(timer.current);
    setMessage(next);
    timer.current=next?setTimeout(()=>{setMessage('');timer.current=null;},3000):null;
  },[]);
  useEffect(()=>()=>{if(timer.current)clearTimeout(timer.current);},[]);
  return [tr(message),notify];
}
