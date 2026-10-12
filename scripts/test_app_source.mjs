// Test-only extraction: compile complete production declarations, never a first line.
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {models} from '../public/models.js';

export function declaration(source,prefix){
 const lines=source.split(/\r?\n/),start=lines.findIndex(line=>line.startsWith(prefix));
 assert.ok(start>=0,`production declaration: ${prefix}`);
 let text='';
 for(let index=start;index<lines.length;index++){
  text+=(text?'\n':'')+lines[index];
  try{new vm.Script(text);return text;}catch(error){if(!(error instanceof SyntaxError))throw error;}
 }
 assert.fail(`production declaration did not parse: ${prefix}`);
}

export function installCreationSelectors(context,source){
 const names=['creationModel','creationRecord','creationJob','creationSlot'];
 const body=names.map(name=>declaration(source,`const ${name}=`)).join('\n');
 Object.assign(context,vm.runInNewContext(body+'\n({'+names.join(',')+'})',{models}));
 return context;
}
