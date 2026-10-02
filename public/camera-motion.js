// Translate the camera in the diagram plane, then recover the node's spherical values.
// Unlike angle-only dragging, moving toward the subject also changes framing distance.
export function dragCamera(start,dx,dy,{sx=70,sy=34,vertical=64,maxElevation=60}={}){
 if(dx===0&&dy===0)return {...start};
 const a=start.h*Math.PI/180,b=start.v*Math.PI/180,r=2.6-start.z*.2;
 const rowX=[sx*.866,0,sx*.5],rowY=[-sy*.5,-vertical,sy*.866];
 const norm=row=>row.reduce((s,x)=>s+x*x,0);
 const p=[r*Math.sin(a)*Math.cos(b),r*Math.sin(b),r*Math.cos(a)*Math.cos(b)].map((n,i)=>n+dx*rowX[i]/norm(rowX)+dy*rowY[i]/norm(rowY));
 const distance=Math.hypot(...p),clamp=(n,lo,hi)=>Math.max(lo,Math.min(hi,n));
 return {h:distance<.001?start.h:Math.round((Math.atan2(p[0],p[2])*180/Math.PI+360)%360),v:distance<.001?start.v:clamp(Math.round(Math.asin(clamp(p[1]/distance,-1,1))*180/Math.PI),-30,maxElevation),z:Math.round(clamp((2.6-distance)*5,0,10)*10)/10};
}
export const nudgeZoom=(zoom,delta)=>Math.round(Math.max(0,Math.min(10,Number(zoom)+delta))*10)/10;
