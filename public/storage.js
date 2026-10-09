import {mergeWorkspaceSnapshots} from './workspace-merge.js?v=88.0';
let db;
function openDatabase(name){return new Promise((resolve,reject)=>{const request=indexedDB.open(name,1);request.onupgradeneeded=()=>{request.result.createObjectStore('assets',{keyPath:'id'});request.result.createObjectStore('state');};request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});}
export async function openStorage({accountId,legacyOwner=false}={}){
 const legacyName='yingxu-studio-v05';
 if(accountId&&!/^[A-Za-z0-9_-]{1,100}$/.test(accountId))throw new Error('账户存储标识无效');
 db=await openDatabase(accountId?legacyName+'-'+accountId:legacyName);
 if(accountId&&legacyOwner&&!await transact('state','readonly',store=>store.get('legacy-migrated'))){
  const old=await openDatabase(legacyName);
  try{
   const read=(store,key)=>new Promise((resolve,reject)=>{const tx=old.transaction(store,'readonly'),r=key===undefined?tx.objectStore(store).getAll():tx.objectStore(store).get(key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
   const [assets,saved,currentAssets,currentState]=await Promise.all([read('assets'),read('state','workspace'),readAssets(),readState()]);
   await new Promise((resolve,reject)=>{const tx=db.transaction(['assets','state'],'readwrite'),known=new Set(currentAssets.map(a=>a.id));for(const a of assets)if(!known.has(a.id))tx.objectStore('assets').put(a);if(!currentState&&saved)tx.objectStore('state').put(saved,'workspace');tx.objectStore('state').put(true,'legacy-migrated');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);});
  }finally{old.close();}
 }
 return db;
}
function transact(name,mode,action){return new Promise((resolve,reject)=>{if(!db){reject(new Error('本地存储不可用'));return;}const tx=db.transaction(name,mode),request=action(tx.objectStore(name));let value;request.onsuccess=()=>{value=request.result;};tx.oncomplete=()=>resolve(value);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||new Error('存储操作已中断'));});}
export const readAssets=()=>transact('assets','readonly',store=>store.getAll());
export const putAsset=asset=>transact('assets','readwrite',store=>store.put(asset));
export const deleteAsset=id=>transact('assets','readwrite',store=>store.delete(id));
export const readState=()=>transact('state','readonly',store=>store.get('workspace'));
export function writeState(value,baseline){return new Promise((resolve,reject)=>{
 if(!db){reject(new Error('本地存储不可用'));return;}
 const tx=db.transaction('state','readwrite'),store=tx.objectStore('state'),read=store.get('workspace');let merged;
 read.onsuccess=()=>{try{merged=mergeWorkspaceSnapshots(read.result,value,baseline);store.put(merged,'workspace');}catch(error){tx.abort();reject(error);}};
 tx.oncomplete=()=>resolve(merged);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||new Error('存储操作已中断'));
});}
