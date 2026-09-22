// Diffuse grazing light, a soft floor reflection and static fine grain.
const layer=document.createElement('div');layer.id='ambient-layer';layer.setAttribute('aria-hidden','true');layer.innerHTML='<canvas></canvas>';document.body.prepend(layer);
const canvas=layer.firstElementChild,ctx=canvas.getContext('2d');
const reduced=matchMedia('(prefers-reduced-motion: reduce)'),off=new URLSearchParams(location.search).get('motion')==='off';
let w=1,h=1,t=0,last=0,raf=0;
const grain=document.createElement('canvas');grain.width=grain.height=160;
const g=grain.getContext('2d'),pixels=g.createImageData(160,160);let seed=73;
for(let i=0;i<pixels.data.length;i+=4){seed=(seed*1664525+1013904223)>>>0;pixels.data[i]=pixels.data[i+1]=pixels.data[i+2]=230;pixels.data[i+3]=(seed/4294967296)*11;}g.putImageData(pixels,0,0);
const texture=ctx.createPattern(grain,'repeat');
function pool(x,y,rx,ry,a,angle=0,color='205,207,220'){
 ctx.save();ctx.translate(x*w,y*h);ctx.rotate(angle);ctx.scale(rx*w,ry*h);const glow=ctx.createRadialGradient(0,0,0,0,0,1);glow.addColorStop(0,`rgba(${color},${a})`);glow.addColorStop(.25,`rgba(${color},${a*.64})`);glow.addColorStop(.6,`rgba(${color},${a*.17})`);glow.addColorStop(1,`rgba(${color},0)`);ctx.fillStyle=glow;ctx.fillRect(-1,-1,2,2);ctx.restore();
}
function paint(){
 ctx.clearRect(0,0,w,h);const travel=Math.sin(t/37000-.65),breathe=Math.sin(t/19000)*.005;
 pool(.66+travel*.18,.08,.5,.91,.078+breathe,-.48);
 pool(.84+travel*.1,.25,.21,.75,.038,-.55,'212,206,229');
 pool(.6+travel*.09,.83,.77,.055,.075,.14);
 pool(.53,.98,.92,.28,.035,0);
 ctx.globalAlpha=.32;ctx.fillStyle=texture;ctx.fillRect(0,0,w,h);ctx.globalAlpha=1;
 canvas.dataset.lightPosition=travel.toFixed(4);
}
function frame(now){raf=0;if(document.hidden||reduced.matches||off){canvas.dataset.motion='paused';return;}if(!last)last=now;if(now-last>=48){t+=Math.min(now-last,100);last=now;paint();}raf=requestAnimationFrame(frame);}
function sync(){cancelAnimationFrame(raf);raf=0;last=0;paint();canvas.dataset.motion=document.hidden||reduced.matches||off?'paused':'running';if(canvas.dataset.motion==='running')raf=requestAnimationFrame(frame);}
function resize(){const b=canvas.getBoundingClientRect(),dpr=Math.min(devicePixelRatio||1,1.25);w=b.width;h=b.height;canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);paint();}
new ResizeObserver(resize).observe(canvas);document.addEventListener('visibilitychange',sync);reduced.addEventListener('change',sync);resize();sync();
