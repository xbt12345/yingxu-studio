import assert from 'node:assert/strict';
import {nextReferenceId,renumberDraftReferences} from '../public/reference-numbering.js';

const fresh={refs:[],prompt:''};
assert.equal(nextReferenceId(fresh,'image'),'图片1');
fresh.refs.push({kind:'image',id:'图片1'});
assert.equal(nextReferenceId(fresh,'image'),'图片2');
assert.equal(nextReferenceId({refs:[],prompt:''},'image'),'图片1');

const legacy={refs:[{kind:'image',id:'图片47'},{kind:'video',id:'视频12'},{kind:'image',id:'图片53'}],prompt:'保留 @图片47，参考 @图片53 和 @视频12',catalogTexts:{extra:'@图片53'}};
const historical=structuredClone(legacy);
renumberDraftReferences(legacy);
assert.deepEqual(legacy.refs.map(r=>r.id),['图片1','视频1','图片2']);
assert.equal(legacy.prompt,'保留 @图片1，参考 @图片2 和 @视频1');
assert.equal(legacy.catalogTexts.extra,'@图片2');
assert.equal(historical.refs[0].id,'图片47');

legacy.refs.splice(0,1);
renumberDraftReferences(legacy,{removedIds:['图片1']});
assert.equal(legacy.refs[1].id,'图片1');
assert.equal(legacy.prompt,'保留 [已移除图片1]，参考 @图片1 和 @视频1');

const reversed={refs:[{kind:'image',id:'图片1',catalogSlot:'second'},{kind:'image',id:'图片2',catalogSlot:'first'}],prompt:'@图片1 在右，@图片2 在左'};
renumberDraftReferences(reversed,{slotOrder:['first','second']});
assert.deepEqual(reversed.refs.map(r=>[r.catalogSlot,r.id]),[['first','图片1'],['second','图片2']]);
assert.equal(reversed.prompt,'@图片2 在右，@图片1 在左');

const pair={mode:'首尾帧',refs:[{kind:'image',id:'图片1',slot:1},{kind:'image',id:'图片2',slot:0}],prompt:'首 @图片2 尾 @图片1'};
renumberDraftReferences(pair);
assert.deepEqual(pair.refs.map(r=>[r.slot,r.id]),[[0,'图片1'],[1,'图片2']]);
assert.equal(pair.prompt,'首 @图片1 尾 @图片2');
console.log(JSON.stringify({newDraftStartsAtOne:true,oldDraftMigration:true,removedMentionDoesNotRetarget:true,slotOrdering:true}));
