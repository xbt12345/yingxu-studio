// Brand assets are independent from layout, video, and pointer animation.
export const brand={name:'映序',latin:'YINGXU',logo:'assets/brand-mark.svg'};
const storageKey='yingxu-v04-logo';
try{const saved=localStorage.getItem(storageKey);if(saved==='text')brand.logo=null;else if(saved&&/^(assets\/brand-|data:image\/)/.test(saved))brand.logo=saved;}catch{}
function apply(value){brand.logo=value;document.querySelectorAll('[data-logo-img]').forEach(el=>{el.hidden=!value;if(value)el.src=value;el.nextElementSibling.hidden=!!value;});try{localStorage.setItem(storageKey,value||'text');}catch{}}
export async function replaceLogo(value){
 if(value instanceof File){const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(value);});apply(data);}else apply(value);
}
export function logo(cls=''){return `<span class="logo-slot ${cls}"><img data-logo-img ${brand.logo?`src="${brand.logo}"`:'hidden'} alt="映序标志"><span ${brand.logo?'hidden':''}>映序</span></span>`;}
