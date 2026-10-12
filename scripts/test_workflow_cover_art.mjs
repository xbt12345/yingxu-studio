import assert from 'node:assert/strict';
import {existsSync,readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import {workflows as builtInWorkflows} from '../public/data.js';
import {workflowCoverProfile,renderWorkflowCover} from '../public/workflow-cover-art.js';
import {taskCover} from '../public/workflow-experience.js';
import {publishedWorkflowCovers,publishedCategoryCovers} from '../public/workflow-cover-media.js?v=91.2';

const catalog=JSON.parse(readFileSync(new URL('../public/local-catalog.json',import.meta.url),'utf8'));
const schemas=JSON.parse(readFileSync(new URL('../public/workflow-interfaces.json',import.meta.url),'utf8')).workflows;
const localWorkflows=catalog.workflows.map(w=>({...w,interface:schemas[w.id]}));
const mainWorkflows=[
  {id:'h3-reference',name:'H3 多参考图生视频',category:'视频生成',output:'video',cover:'award-poster.jpg'},
  {id:'bernini-edit',name:'Bernini 视频编辑',category:'视频编辑',output:'video',cover:'award-poster.jpg'}
];
const allWorkflows=[...localWorkflows,...builtInWorkflows,...mainWorkflows];
const find=id=>allWorkflows.find(w=>w.id===id);
const sampleIds=['local-card-1','local-card-2','local-card-13','local-card-72','h3-reference','local-card-136'];

function freezeTree(value){
  if(value&&typeof value==='object'&&!Object.isFrozen(value)){
    Object.freeze(value);
    for(const child of Object.values(value))freezeTree(child);
  }
  return value;
}
function decodeAttribute(value){
  return value.replace(/&(?:amp|quot|apos|lt|gt|#\d+|#x[\da-f]+);/gi,entity=>{
    const named={'&amp;':'&','&quot;':'"','&apos;':"'",'&lt;':'<','&gt;':'>'};
    if(entity.toLowerCase() in named)return named[entity.toLowerCase()];
    const hex=/^&#x/i.test(entity),number=parseInt(entity.slice(hex?3:2,-1),hex?16:10);
    return String.fromCodePoint(number);
  });
}
// Parse quoted attributes as units: escaped text containing "onerror=" must not
// be mistaken for an executable attribute, and an actual breakout must be caught.
function elements(html){
  return [...html.matchAll(/<([a-z][\w:-]*)\b([^>]*)>/gi)].map(([,tag,raw])=>({
    tag:tag.toLowerCase(),
    attrs:[...raw.matchAll(/(?:^|\s)([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))/g)]
      .map(([,name,double,single,plain])=>({name:name.toLowerCase(),value:decodeAttribute(double??single??plain)}))
  }));
}
function sources(html){
  return elements(html).filter(el=>['img','image','video','source'].includes(el.tag))
    .flatMap(el=>el.attrs.filter(a=>['src','href','xlink:href'].includes(a.name)).map(a=>a.value));
}
function assertSafeMarkup(html){
  for(const el of elements(html)){
    assert(!['script','iframe','object','embed'].includes(el.tag),`unexpected active element: ${el.tag}`);
    for(const attr of el.attrs){
      assert(!/^on/i.test(attr.name),`event-handler attribute escaped its source: ${attr.name}`);
      if(['src','href','xlink:href'].includes(attr.name)){
        const normalized=attr.value.replace(/[\u0000-\u0020\u007f]/g,'').toLowerCase();
        assert(!/^(?:javascript|vbscript|file|media-source):/.test(normalized),`unsafe media protocol: ${attr.value}`);
        assert(!/^data:(?!image\/(?:png|jpeg|webp|gif|avif);)/.test(normalized),`unexpected executable data URI: ${attr.value}`);
      }
    }
  }
}
function assertPureDiagram(html){
  assert.match(html,/<svg\b/,'a media failure must still explain the operation');
  assert(!elements(html).some(el=>['img','image','video','source'].includes(el.tag)),
    'the fallback must not retry a failed media resource');
  assert.equal(sources(html).length,0);
  assert(!/原图\s*(?:→|&rarr;|&#8594;)\s*历史|历史结果|历史对照|原图对照/.test(html),
    'a pure diagram cannot claim to show a real historical comparison');
}

test('every local, built-in and main workflow has a usable C operation cover without changing its inputs',()=>{
  assert.equal(localWorkflows.length,151,'this fixture must include the complete current local catalog');
  const before=structuredClone(allWorkflows);
  freezeTree(allWorkflows);
  for(const w of allWorkflows){
    const profile=workflowCoverProfile(w);
    assert.equal(typeof profile?.kind,'string',`${w.id}: missing operation kind`);
    assert(profile.kind.trim(),`${w.id}: empty operation kind`);
    assert.equal(typeof profile?.label,'string',`${w.id}: missing visible operation label`);
    assert(profile.label.trim(),`${w.id}: empty visible operation label`);
    const html=renderWorkflowCover(w,{evidence:'sample'});
    assert.equal(typeof html,'string',w.id);
    assert.match(html,/<svg\b/,`${w.id}: operation overlay missing`);
    assert(sources(html).length>0,`${w.id}: C sample lost its picture`);
    assertSafeMarkup(html);
  }
  assert.deepEqual(allWorkflows,before,'covers must not change graph fields, schema bindings or workflow metadata');
});

test('the six user-selected examples retain distinct operations and visible labels',()=>{
  const profiles=sampleIds.map(id=>workflowCoverProfile(find(id)));
  assert.equal(new Set(profiles.map(p=>p.kind)).size,sampleIds.length);
  assert.equal(new Set(profiles.map(p=>p.label)).size,sampleIds.length);
  for(const [index,id] of sampleIds.entries()){
    const visibleText=renderWorkflowCover(find(id),{evidence:'sample'}).replace(/<[^>]*>/g,' ');
    assert(visibleText.includes(profiles[index].label),`${id}: the operation must be visible, not only stored in its profile`);
  }
  for(const id of ['local-card-72','local-card-75']){
    const p=workflowCoverProfile(find(id));
    assert.match(p.kind,/camera|angle|view/i,`${id}: multi-view must use a camera operation`);
    assert.match(p.label,/视角|机位/,`${id}: do not flatten cameras into a generic set of pictures`);
  }
  const clothes=workflowCoverProfile(find('local-card-61'));
  assert.match(clothes.label,/视频/,'video clothing editing must not be labeled as image clothing editing');
  assert.match(clothes.label,/换衣|换装|衣服/);
  assert.match(workflowCoverProfile(find('local-card-133')).label,/白底|背景/,
    'background removal deserves its own operation instead of generic enhancement');
  assert.match(workflowCoverProfile(find('local-card-136')).label,/目录|选帧|素材读取/,
    'batch loading is a directory/frame selection operation, not image generation');
});

test('category covers describe the category regardless of which tool represents it',()=>{
  for(const category of catalog.categories){
    const family=localWorkflows.filter(w=>w.category===category);
    assert(family.length,category);
    const expected=workflowCoverProfile(family[0],true);
    for(const w of family)assert.deepEqual(workflowCoverProfile(w,true),expected,
      `${category}: the cover must not drift with the selected tool's name or history`);
    const changedRepresentative={...family[0],name:'视频换衣 九视角 局部重绘',id:'unrelated-representative'};
    assert.deepEqual(workflowCoverProfile(changedRepresentative,true),expected,
      `${category}: representative selection must not change a category's operation`);
  }
});

test('multiple renderings have no duplicate SVG IDs or cross-card fragment references',()=>{
  const htmlRows=[...allWorkflows,...sampleIds.map(find)].map(w=>renderWorkflowCover(w,{evidence:'sample'}));
  const used=new Set();
  for(const [index,html] of htmlRows.entries()){
    const ids=elements(html).flatMap(el=>el.attrs.filter(a=>a.name==='id').map(a=>a.value));
    const localIds=new Set(ids);
    assert.equal(localIds.size,ids.length,`card ${index}: duplicate local ID`);
    for(const id of ids){assert(!used.has(id),`card ${index}: ID ${id} collides with another cover`);used.add(id);}
    const references=[...html.matchAll(/url\(\s*['"]?#([^)'"\s]+)['"]?\s*\)/g)].map(m=>m[1]);
    references.push(...elements(html).flatMap(el=>el.attrs
      .filter(a=>['href','xlink:href'].includes(a.name)&&a.value.startsWith('#')).map(a=>a.value.slice(1))));
    for(const id of references)assert(localIds.has(id),`card ${index}: fragment ${id} resolves outside this cover`);
  }
});

test('real original and output URLs are rendered as evidence without mutating their sources',()=>{
  // These image operations really accept references, but use different layouts.
  // Checking only the generic editor would miss a camera/upscale layout that
  // labels a comparison while silently dropping one of the two real sources.
  const operations=['local-card-2','local-card-13','local-card-72','local-card-74','local-card-90','local-card-133'];
  const cases=[
    {primary:'/api/assets/result-b/file?size=large&version=2',input:'/api/assets/original-a/file',evidence:'comparison'},
    {primary:'blob:http://localhost:8770/current-result',input:'blob:http://localhost:8770/current-original',evidence:'comparison'},
    {primary:'https://media.example.test/results/result-b.png',input:'https://media.example.test/originals/original-a.png',evidence:'comparison'}
  ];
  for(const media of cases){
    const before=structuredClone(media);freezeTree(media);
    for(const id of operations){
      const html=renderWorkflowCover(find(id),media),renderedSources=sources(html);
      assert(renderedSources.includes(media.primary),`${id}: the saved result source must remain available`);
      assert(renderedSources.includes(media.input),`${id}: the same historical job original must remain available`);
      assert.match(html,/原图/);assert.match(html,/历史|结果/);
      assertSafeMarkup(html);
    }
    assert.deepEqual(media,before);
  }
  const primary='/api/assets/video-poster/file';
  assert(sources(renderWorkflowCover(find('h3-reference'),{primary,evidence:'history'})).includes(primary),
    'a real video poster can supply the primary picture');
});

test('unsafe media schemes and attribute breakouts cannot become executable cover markup',()=>{
  const w=find('local-card-2');
  const unsafe=[
    'javascript:alert(1)','JaVaScRiPt:alert(1)',' \tjavascript:alert(1)','java\nscript:alert(1)',
    'vbscript:msgbox(1)','data:text/html,<script>alert(1)</script>',
    'file:///C:/private/secret.png','media-source:untrusted',
    '/\\untrusted.example.test/image.png','https:\\untrusted.example.test/image.png'
  ];
  for(const uri of unsafe){
    const html=renderWorkflowCover(w,{primary:uri,input:uri,evidence:'comparison'});
    assertSafeMarkup(html);
    assert(!sources(html).includes(uri),`unsafe source was accepted: ${uri}`);
  }
  for(const uri of ['/api/assets/picture/file?name=" onerror="alert(1)',
                    'https://media.example.test/image.png?x=\"><script>alert(1)</script>']){
    const html=renderWorkflowCover(w,{primary:uri,input:uri,evidence:'comparison'});
    assertSafeMarkup(html);
  }
  assertSafeMarkup(renderWorkflowCover({id:'unknown',name:'\"><script>alert(1)</script>',category:'\"><img src=x onerror=alert(1)>',cover:'javascript:alert(1)'},{evidence:'sample'}));
});

test('an incomplete or rejected comparison cannot claim a complete historical original/result pair',()=>{
  for(const media of [
    {primary:'javascript:alert(1)',input:'/api/assets/original-a/file',evidence:'comparison'},
    {primary:'/api/assets/result-b/file',input:'javascript:alert(1)',evidence:'comparison'},
    {primary:'/api/assets/result-b/file',evidence:'comparison'},
    {primary:'javascript:alert(1)',input:'assets/coast.jpg',evidence:'published-comparison'},
    {primary:'assets/coast.jpg',input:'javascript:alert(1)',evidence:'published-comparison'},
    {primary:'assets/coast.jpg',evidence:'published-comparison'}
  ]){
    const html=renderWorkflowCover(find('local-card-2'),media);
    assertSafeMarkup(html);
    assert(!/原图\s*(?:→|&rarr;|&#8594;)\s*(?:历史|示例)|历史对照|原图对照/.test(html),
      'missing evidence must not be shown with a complete comparison label');
  }
});

test('an explicitly supplied sample picture remains a sample rather than becoming historical evidence',()=>{
  const media=freezeTree({primary:'assets/coast.jpg',input:'assets/forest.jpg',evidence:'sample'});
  const html=renderWorkflowCover(find('local-card-2'),media);
  assert(sources(html).includes(media.primary),'the chosen sample picture can be used');
  assert(!/历史|原图对照/.test(html),'a non-empty media URL does not establish a real completed task');
  assertSafeMarkup(html);
});

test('published cover media is self-contained, distinct from personal history and preserves category purpose',()=>{
  assert(Object.keys(publishedWorkflowCovers).length,'the release must include the requested workflow covers');
  for(const [category,entries] of [[false,publishedWorkflowCovers],[true,publishedCategoryCovers]]){
    for(const [key,media] of Object.entries(entries)){
      const w=category?localWorkflows.find(w=>w.category===key):find(key);
      assert(w,`published cover has no catalog owner: ${key}`);
      assert(media.primary,`${key}: a published cover needs its primary image`);
      assert(Object.keys(media).every(key=>['primary','input','inputs'].includes(key)),`${key}: only public media may be exported`);
      const paths=[media.primary,media.input,...(media.inputs||[])].filter(Boolean);
      for(const path of paths){
        assert.match(path,/^assets\/workflow-covers\/[\w.-]+\.(?:png|jpe?g|webp|avif)$/i,`${key}: the cover must be a portable static resource`);
        assert(existsSync(new URL('../public/'+path,import.meta.url)),`${key}: missing published cover ${path}`);
      }
      const before=structuredClone(media),html=taskCover(w,[],category);
      assert(sources(html).includes(media.primary),`${key}: a clean workspace must show the published cover`);
      assert.match(html,/data-cover-source="published"/);
      assert.match(html,/示例/);assert(!/历史/.test(html),'release examples are not a new user\'s history');
      if(media.input){assert(sources(html).includes(media.input));assert.match(html,/示例原图\s*→\s*示例结果/);}
      assert.equal(elements(html).find(el=>el.attrs.some(a=>a.name==='data-cover-kind'))
        ?.attrs.find(a=>a.name==='data-cover-kind')?.value,workflowCoverProfile(w,category).kind);
      if(category)for(const representative of localWorkflows.filter(item=>item.category===key)){
        assert.equal(taskCover(representative,[],true),html,'a category cover must not depend on its first workflow');
      }
      const skipped=taskCover(w,[],category,[],{skipPublished:true});
      assert.match(skipped,/data-cover-source="sample"/);assert(!sources(skipped).some(src=>paths.includes(src)));
      assertPureDiagram(taskCover(w,[],category,[],{omitImages:true}));
      assert.deepEqual(media,before);assertSafeMarkup(html);
    }
  }
});

test('real available personal history wins over published examples without reviving removed results',()=>{
  const [id,published]=Object.entries(publishedWorkflowCovers)[0],w=find(id);
  const original='/api/assets/personal-original/file',primary='/api/assets/personal-result/file';
  const row={o:{type:'image',src:primary},j:{real:true,status:'done',snapshot:{workflowId:id,refs:[{kind:'image',src:original}]}}};
  const before=structuredClone(row),html=taskCover(w,[row]);
  assert(sources(html).includes(primary));assert(sources(html).includes(original));
  assert(!sources(html).includes(published.primary));assert.match(html,/data-cover-source="history"/);
  for(const invalid of [
    {...row,j:{...row.j,real:false}},
    {...row,j:{...row.j,status:'running'}},
    {...row,o:{...row.o,removedAt:123}},
    {...row,o:{...row.o,available:false}},
    {...row,o:{type:'video',src:'/without-poster.mp4'}},
    {...row,o:{type:'image',src:''}}
  ]){
    const fallback=taskCover(w,[invalid]);
    assert.match(fallback,/data-cover-source="published"/);assert(sources(fallback).includes(published.primary));
    assert(sources(taskCover(w,[row,invalid])).includes(primary),'an unavailable last row must not hide earlier usable history');
  }
  assert.deepEqual(row,before);
});

test('omitImages is a pure operation fallback even when real comparison URLs were supplied',()=>{
  const media=freezeTree({primary:'/api/assets/result-b/file',input:'/api/assets/original-a/file',evidence:'comparison',omitImages:true});
  const before=structuredClone(media);
  for(const id of sampleIds){
    const html=renderWorkflowCover(find(id),media);
    assertPureDiagram(html);assertSafeMarkup(html);
    assert(!html.includes(media.primary)&&!html.includes(media.input),'failed resources must not be retried in hidden SVG markup');
  }
  assert.deepEqual(media,before);
});

test('cover art leaves connection state and billing claims to the owning workflow card',()=>{
  const w={...find('local-card-1'),live:true,catalogConnected:true,catalogPendingApi:false,catalogBlocked:false,
    state:{label:'STATE_SENTINEL'},catalogConnection:{label:'STATE_SENTINEL'},cost:'COST_SENTINEL',price:'PRICE_SENTINEL'};
  const before=structuredClone(w);freezeTree(w);
  const html=renderWorkflowCover(w,{evidence:'sample'});
  assert(!/STATE_SENTINEL|COST_SENTINEL|PRICE_SENTINEL|已接入|交互演示|待接入|已实测|积分|扣费|费用|余额/.test(html),
    'a layout sample must not invent connection state, execution success or billing');
  assert.deepEqual(w,before);
});

test('the production image-error boundary advances through each available source without retrying failed media',()=>{
  const app=readFileSync(new URL('../public/app.js',import.meta.url),'utf8');
  const start=app.indexOf("main.addEventListener('error',");
  const end=app.indexOf('\nlet sidebarMarkup=',start);
  assert(start>=0&&end>start,'the production cover error listener must be available for execution');
  const listenerSource=app.slice(start,end);
  const publishedId=Object.keys(publishedWorkflowCovers)[0];
  const noPublished={id:'no-published-cover',name:'No published cover',category:'no-published-category'};
  const cases=[[find(publishedId),false,true],[find(publishedId),false,false],[noPublished,false,true],[noPublished,false,false]];
  const publishedCategory=Object.keys(publishedCategoryCovers)[0];
  if(publishedCategory)cases.push([localWorkflows.find(w=>w.category===publishedCategory),true,true]);
  for(const [w,category,withHistory] of cases){
    const id=w.id,assets=freezeTree([]);
    const history=freezeTree([{o:{type:'image',src:'/api/assets/failing-result/file'},
      j:{real:true,status:'done',snapshot:{workflowId:id,refs:[{kind:'image',src:'/api/assets/failing-original/file'}]}}}]);
    const historyBefore=structuredClone(history);
    const cover={dataset:{coverWorkflow:id,coverCategory:String(category)},innerHTML:taskCover(w,withHistory?history:[],category,assets),
      querySelector(selector){assert.equal(selector,'.cover-art');return {dataset:{coverSource:this.innerHTML.match(/data-cover-source="([^"]+)"/)?.[1]}};}};
    if(withHistory){
      assert(sources(cover.innerHTML).includes('/api/assets/failing-result/file'),'the fixture must start with actual historical media');
      assert.match(cover.innerHTML,/原图\s*→\s*历史结果/);
    }
    let listener;
    const calls=[];
    const context=vm.createContext({
      main:{addEventListener(type,handler,capture){
        assert.equal(type,'error');assert.equal(capture,true,'image load errors require the capture listener');
        assert.equal(listener,undefined);listener=handler;
      }},
      workflows:[w],workspace:{assets},
      taskCover(workflow,rows,isCategory,currentAssets,options={}){
        assert.equal(workflow,w);assert.equal(currentAssets,assets);
        calls.push({rowCount:rows.length,category:isCategory,omitImages:options.omitImages,skipPublished:options.skipPublished});
        return taskCover(workflow,rows,isCategory,currentAssets,options);
      }
    });
    vm.runInContext(listenerSource,context);
    assert.equal(typeof listener,'function');
    const failedImage={tagName:'IMG',closest(selector){assert.equal(selector,'.task-cover[data-cover-workflow]');return cover;}};

    const transitions=[],published=category?publishedCategoryCovers[w.category]:publishedWorkflowCovers[id];
    for(let step=0;step<4&&cover.querySelector('.cover-art').dataset.coverSource!=='diagram';step++){
      const source=cover.querySelector('.cover-art').dataset.coverSource,failedSources=sources(cover.innerHTML);
      listener({target:failedImage});
      const next=cover.querySelector('.cover-art').dataset.coverSource;
      transitions.push([source,next]);
      assert.equal(next,source==='history'?(published?'published':'sample'):source==='published'?'sample':'diagram');
      assert.deepEqual(calls.at(-1),{rowCount:0,category,omitImages:source==='sample',skipPublished:source!=='history'});
      assert(!sources(cover.innerHTML).some(src=>failedSources.includes(src)),`${id}: a failing source must never be requested again`);
      assert(!/历史|原图对照/.test(cover.innerHTML),'release media and scenery must not retain personal history labels');
      assert.equal(elements(cover.innerHTML).find(el=>el.attrs.some(a=>a.name==='data-cover-kind'))
        ?.attrs.find(a=>a.name==='data-cover-kind')?.value,workflowCoverProfile(w,category).kind,
        'recovery must preserve the category/tool operation');
    }
    assert.equal(transitions.length,(withHistory?1:0)+(published?1:0)+1);
    assert.equal(cover.dataset.coverFallback,'diagram');
    assertPureDiagram(cover.innerHTML);assertSafeMarkup(cover.innerHTML);

    // Forward delayed duplicate errors explicitly. Real detached IMG errors no
    // longer reach main; the terminal guard must still make repeated delivery
    // harmless rather than cycling back to another network image.
    const terminalHTML=cover.innerHTML;
    for(let repeat=0;repeat<4;repeat++)listener({target:failedImage});
    assert.equal(calls.length,transitions.length,'terminal recovery must not render or request images again');
    assert.equal(cover.innerHTML,terminalHTML);
    assert.deepEqual(history,historyBefore,'error recovery must not alter saved original/result identities');

    listener({target:{tagName:'VIDEO',closest(){assert.fail('non-image errors must not enter the cover recovery');}}});
    listener({target:{tagName:'IMG',closest(){return null;}}});
    listener({target:{tagName:'IMG',closest(){return {dataset:{coverWorkflow:'missing-workflow'}};}}});
    assert.equal(calls.length,transitions.length,'unrelated media errors must not trigger cover rendering');
  }
});
