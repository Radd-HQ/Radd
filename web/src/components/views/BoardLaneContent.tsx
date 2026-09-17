import { useEffect, useRef, useState, type ReactNode } from "react";

/** Keep complete lane headers available without mounting the whole matrix.
 * Once visited, a lane stays mounted so selections and drag targets survive. */
export function BoardLaneContent({children}:{children:()=>ReactNode}) {
  const ref=useRef<HTMLDivElement>(null);
  const [visited,setVisited]=useState(false);
  useEffect(()=>{
    if(visited||!ref.current) return;
    const observer=new IntersectionObserver(entries=>{
      if(entries.some(e=>e.isIntersecting)) setVisited(true);
    },{rootMargin:"200px"});
    observer.observe(ref.current);
    return ()=>observer.disconnect();
  },[visited]);
  return <div ref={ref}>{visited?children():<div className="h-80" aria-label="Issues load when this lane is visible" />}</div>;
}
