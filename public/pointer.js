// Pointer activation must never move the click target between down and up.
export function magneticCTA(stage, button) {
  const reduce=matchMedia('(prefers-reduced-motion: reduce)');
  const fine=matchMedia('(hover:hover) and (pointer:fine)');
  let x=0,y=0,tx=0,ty=0,vx=0,vy=0,raf=0,last=0,acc=0;
  let pressed=false,keyboard=false,inside=false;
  const position=()=>{button.style.left=x+'px';button.style.top=y+'px';};
  function stop(){cancelAnimationFrame(raf);raf=0;vx=vy=0;}
  function tick(now){acc+=Math.min(2000,Math.max(0,now-last));last=now;while(acc>=1000/60){vx=(vx+(tx-x)*.18)*.68;vy=(vy+(ty-y)*.18)*.68;x+=vx;y+=vy;acc-=1000/60;}position();if(Math.abs(tx-x)+Math.abs(ty-y)+Math.abs(vx)+Math.abs(vy)>.15)raf=requestAnimationFrame(tick);else{raf=0;x=tx;y=ty;position();}}
  function start(){if(!raf){last=performance.now();acc=0;raf=requestAnimationFrame(tick);}}
  function center(immediate=false){tx=stage.clientWidth/2;ty=stage.clientHeight/2;if(immediate||reduce.matches||!fine.matches){stop();x=tx;y=ty;position();}else start();}
  function move(e){inside=true;if(pressed||keyboard&&button===document.activeElement||reduce.matches||!fine.matches)return;const r=stage.getBoundingClientRect(),mx=button.offsetWidth/2+18,my=button.offsetHeight/2+62;tx=Math.max(mx,Math.min(r.width-mx,e.clientX-r.left));ty=Math.max(my,Math.min(r.height-my,e.clientY-r.top));start();}
  function leave(){inside=false;if(!pressed)center();}
  function down(){keyboard=false;pressed=true;stop();tx=x;ty=y;}
  function up(){pressed=false;if(!inside)center();}
  function key(e){if(e.key==='Tab'){keyboard=true;}}
  function pointerMode(){keyboard=false;}
  function focus(){if(keyboard)center(true);}
  function preference(){center(true);}
  const resize=new ResizeObserver(()=>{if(!inside&&!pressed)center(true);});resize.observe(stage);
  document.addEventListener('pointerdown',pointerMode,true);
  document.addEventListener('keydown',key,true);
  document.addEventListener('pointerup',up);
  button.addEventListener('pointerdown',down);
  button.addEventListener('pointercancel',up);
  button.addEventListener('focus',focus);
  stage.addEventListener('pointermove',move);
  stage.addEventListener('pointerleave',leave);
  reduce.addEventListener('change',preference);fine.addEventListener('change',preference);
  center(true);
  return()=>{stop();resize.disconnect();document.removeEventListener('pointerdown',pointerMode,true);document.removeEventListener('keydown',key,true);document.removeEventListener('pointerup',up);button.removeEventListener('pointerdown',down);button.removeEventListener('pointercancel',up);button.removeEventListener('focus',focus);stage.removeEventListener('pointermove',move);stage.removeEventListener('pointerleave',leave);reduce.removeEventListener('change',preference);fine.removeEventListener('change',preference);};
}
