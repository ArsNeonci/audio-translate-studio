const props={width:20,height:20,viewBox:'0 0 24 24',fill:'none',stroke:'currentColor',strokeWidth:1.8,strokeLinecap:'round' as const,strokeLinejoin:'round' as const,'aria-hidden':true as const};
export function EyeIcon(){return <svg {...props}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>;}
export function TrashIcon(){return <svg {...props}><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/></svg>;}
export function DownloadIcon(){return <svg {...props}><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/></svg>;}
export function RegenerateIcon(){return <span className="regenerate-icon" aria-hidden="true"/>;}
