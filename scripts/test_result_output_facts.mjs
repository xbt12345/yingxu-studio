import test from 'node:test';
import assert from 'node:assert/strict';
import {resultMediaMarkup,resultOutputFacts,resultOutputParametersMarkup,resultExtension} from '../public/result-media.js';

test('GIF output parameters use encoded delay rather than requested frame rate',()=>{
 const output=Object.freeze({type:'image',src:'/api/media/sample/0.gif',width:512,height:512,frame_rate:6.25,frame_count:2,duration:.32,metadata_source:'stored_file',settings:{frame_rate:6}});
 const facts=resultOutputFacts(output);
 assert.equal(facts.find(row=>row.key==='frame_rate').value,'6.25 FPS');
 assert.equal(facts.find(row=>row.key==='frame_count').value,'2 帧');
 assert.equal(facts.find(row=>row.key==='duration').value,'0.32 秒');
 assert.equal(resultExtension(output),'gif');
});

test('saved video duration and frame count remain different from generation request',()=>{
 const output={type:'video',src:'/api/media/sample/0.mp4',width:512,height:512,frame_rate:25,frame_count:81,duration:3.24,metadata_source:'file_probe',settings:{frame_rate:16,duration:1.845}};
 const markup=resultOutputParametersMarkup(output);
 assert.ok(markup.includes('实际帧率')&&markup.includes('25 FPS'));
 assert.ok(markup.includes('81 帧')&&markup.includes('3.24 秒'));
 assert.ok(!markup.includes('16 FPS')&&!markup.includes('1.845'));
});

test('unknown metadata never borrows request fields or claims measured facts',()=>{
 assert.deepEqual(resultOutputFacts({type:'video',settings:{width:1024,height:1024,frame_rate:24,duration:2}}),[]);
 assert.deepEqual(resultOutputFacts({type:'video',metadata_source:'workflow_inputs',width:1024,height:1024,frame_rate:24,duration:2}),[]);
 assert.equal(resultOutputParametersMarkup({type:'video',frame_rate:24,duration:2}), '');
});

test('result card markup remains unchanged unless dialog explicitly opts in',()=>{
 const output={type:'video',src:'/api/media/sample/0.mp4',width:512,height:512,frame_rate:25,frame_count:81,duration:3.24,metadata_source:'stored_file'};
 assert.ok(!resultMediaMarkup(output).includes('result-output-facts'));
 assert.ok(!resultMediaMarkup(output,{preview:true,showFacts:true}).includes('result-output-facts'));
 assert.ok(resultMediaMarkup(output,{showFacts:true}).includes('result-output-facts'));
});

test('still images show measured resolution without a one-frame duration panel',()=>{
 const facts=resultOutputFacts({type:'image',src:'/api/media/sample/0.png',width:736,height:736,frame_count:1,metadata_source:'image_header'});
 assert.deepEqual(facts,[{key:'resolution',label:'实际分辨率',value:'736 × 736'}]);
 assert.deepEqual(resultOutputFacts({type:'audio',duration:1.845,frame_rate:48000,frame_count:91,metadata_source:'file_probe'}),[{key:'duration',label:'实际时长',value:'1.845 秒'}]);
});

test('fractional rates and malformed facts are handled without unsafe markup',()=>{
 assert.equal(resultOutputFacts({type:'video',frame_rate:'30000/1001',metadata_source:'stored_file'})[0].value,'29.97 FPS');
 assert.deepEqual(resultOutputFacts({type:'video',width:true,height:512,frame_rate:Infinity,frame_count:-1,duration:'<script>',metadata_source:'stored_file'}),[]);
 const markup=resultOutputParametersMarkup({type:'image',width:512,height:512,metadata_source:'file'},{title:'<script>test</script>'});
 assert.ok(!markup.includes('<script>'));
});
