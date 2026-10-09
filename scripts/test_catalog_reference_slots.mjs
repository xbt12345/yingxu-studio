import test from 'node:test';
import assert from 'node:assert/strict';
import {catalogReferenceLayout,openCatalogReferenceSlot,closeCatalogReferenceSlot,compactCatalogReferenceSlots} from '../public/catalog-reference-slots.js';

const cfg={referencePolicy:{presentation:'progressive',minImages:1},media:Array.from({length:9},(_,i)=>({id:String(i),kind:'image',required:i===0}))};

test('one required reference opens first, adding reveals only real ports',()=>{
 const d={refs:[]};
 assert.deepEqual(catalogReferenceLayout(cfg,d).visible.map(slot=>slot.id),['0']);
 assert.equal(openCatalogReferenceSlot(cfg,d),'1');
 assert.deepEqual(catalogReferenceLayout(cfg,d).visible.map(slot=>slot.id),['0','1']);
 assert.equal(catalogReferenceLayout(cfg,d).boundCount,0);
 assert.equal(cfg.media[1].required,false);
});

test('all existing and historical references remain visible, including gaps',()=>{
 const d={refs:[{catalogSlot:'0'},{catalogSlot:'7'}],catalogOpenSlots:['missing','4']};
 assert.deepEqual(catalogReferenceLayout(cfg,d).visible.map(slot=>slot.id),['0','4','7']);
 assert.equal(catalogReferenceLayout(cfg,d).boundCount,2);
 assert.equal(openCatalogReferenceSlot(cfg,d),'1');
 assert.equal(d.catalogOpenSlots.includes('missing'),false);
 closeCatalogReferenceSlot(d,'4');
 assert.deepEqual(catalogReferenceLayout(cfg,d).visible.map(slot=>slot.id),['0','1','7']);
 assert.deepEqual(d.refs,[{catalogSlot:'0'},{catalogSlot:'7'}]);
});

test('cannot add beyond reviewed port count, closing first does not remove requirement',()=>{
 const d={refs:[]};
 for(let i=1;i<9;i++)assert.equal(openCatalogReferenceSlot(cfg,d),String(i));
 assert.equal(openCatalogReferenceSlot(cfg,d),null);
 assert.equal(catalogReferenceLayout(cfg,d).visible.length,9);
 closeCatalogReferenceSlot(d,'0');
 assert.equal(catalogReferenceLayout(cfg,d).visible[0].id,'0');
});

test('other workflows keep every port and mixed media keep required video visible',()=>{
 const ordinary={media:cfg.media};
 assert.equal(catalogReferenceLayout(ordinary,{}).visible,ordinary.media);
 assert.equal(openCatalogReferenceSlot(ordinary,{}),null);
 const mixed={...cfg,media:[{id:'video',kind:'video',required:true},...cfg.media]};
 assert.deepEqual(catalogReferenceLayout(mixed,{refs:[]}).visible.map(slot=>slot.id),['video','0']);
});

test('removing first reference promotes remaining images without losing identities',()=>{
 const d={refs:[{id:'图片2',catalogSlot:'1',kind:'image',serverAssetId:'original-2'},{id:'图片3',catalogSlot:'2',kind:'image',serverAssetId:'original-3'}],catalogOpenSlots:['1','2','3']};
 compactCatalogReferenceSlots(cfg,d,'0');
 assert.deepEqual(d.refs.map(ref=>[ref.id,ref.catalogSlot,ref.serverAssetId]),[['图片2','0','original-2'],['图片3','1','original-3']]);
 assert.deepEqual(catalogReferenceLayout(cfg,d).visible.map(slot=>slot.id),['0','1','2']);
 assert.equal(catalogReferenceLayout(cfg,d).boundCount,2);
});
