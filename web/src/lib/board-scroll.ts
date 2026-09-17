import { useEffect, useRef, type DragEvent, type RefObject } from "react";

/** Native drag does not reliably auto-scroll nested overflow containers. Keep
 * horizontal board movement and the hovered column's vertical edge reachable. */
export function useBoardDragScroll(root:RefObject<HTMLDivElement|null>,active:boolean) {
  const point=useRef<{x:number;y:number}|null>(null);
  useEffect(()=>{
    if(!active) {point.current=null;return;}
    let frame=0;
    const tick=()=>{
      const p=point.current, board=root.current;
      if(p&&board) {
        const r=board.getBoundingClientRect();
        const speed=(n:number,start:number,end:number)=>n<start+40?-12:n>end-40?12:0;
        if(p.y>=r.top&&p.y<=r.bottom&&p.x>=r.left&&p.x<=r.right) {
          board.scrollLeft+=speed(p.x,r.left,r.right);
          const column=document.elementFromPoint(p.x,p.y)?.closest<HTMLElement>("[data-column-scroll]");
          if(column) {const c=column.getBoundingClientRect();column.scrollTop+=speed(p.y,c.top,c.bottom);}
          else board.scrollTop+=speed(p.y,r.top,r.bottom);
        }
      }
      frame=requestAnimationFrame(tick);
    };
    frame=requestAnimationFrame(tick);
    return ()=>cancelAnimationFrame(frame);
  },[active,root]);
  return (event:DragEvent)=>{point.current={x:event.clientX,y:event.clientY};};
}
