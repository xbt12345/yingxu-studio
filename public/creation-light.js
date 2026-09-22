// Decorative only. No prompt data or generation state is read or changed here.
const motionQuery=matchMedia('(prefers-reduced-motion: reduce)');
const motionOff=new URLSearchParams(location.search).get('motion')==='off';
document.documentElement.dataset.motion=motionOff?'off':'on';

// Specular light follows the pointer; the actual clickable rectangle stays still.
const controlSelector='.button,.intent-control,.small-button,.icon-button,.control:not(.text-control),.category,.segment';
let active=null,raf=0,x=50,y=15,targetX=50,targetY=15,last=0;
function finishHighlight(){cancelAnimationFrame(raf);raf=0;last=0;active?.removeAttribute('data-glass-lit');active=null;}
function illuminate(now){
  raf=0;if(!active?.isConnected||document.hidden||motionQuery.matches||motionOff){finishHighlight();return;}
  const dt=last?Math.min(now-last,50):16;last=now;const ease=1-Math.exp(-dt/65);
  x+=(targetX-x)*ease;y+=(targetY-y)*ease;
  active.style.setProperty('--glass-x',x.toFixed(2)+'%');active.style.setProperty('--glass-y',y.toFixed(2)+'%');
  if(Math.abs(x-targetX)+Math.abs(y-targetY)>.05)raf=requestAnimationFrame(illuminate);
}
document.addEventListener('pointermove',e=>{
  if(e.pointerType!=='mouse'||motionQuery.matches||motionOff)return;
  const el=e.target.closest(controlSelector);
  if(!el||el.matches(':disabled,[aria-disabled=true]')){finishHighlight();return;}
  if(active!==el){finishHighlight();active=el;x=50;y=15;el.setAttribute('data-glass-lit','');}
  const r=el.getBoundingClientRect();targetX=(e.clientX-r.left)/r.width*100;targetY=(e.clientY-r.top)/r.height*100;
  if(!raf)raf=requestAnimationFrame(illuminate);
},{passive:true});
document.addEventListener('pointerleave',finishHighlight);
document.addEventListener('visibilitychange',()=>{document.documentElement.dataset.pageHidden=String(document.hidden);if(document.hidden)finishHighlight();});
motionQuery.addEventListener('change',finishHighlight);

