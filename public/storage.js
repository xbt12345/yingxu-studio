import {mergeWorkspaceSnapshots} from './workspace-merge.js?v=75.1';
let db;
export function openStorage(){return new Promise((resolve,reject)=>{const request=indexedDB.open('yingxu-studio-v05',1);request.onupgradeneeded=()=>{request.result.createObjectStore('assets',{keyPath:'id'});request.result.createObjectStore('state');};request.onsuccess=()=>{db=request.result;resolve(db);};request.onerror=()=>reject(request.error);});}
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
