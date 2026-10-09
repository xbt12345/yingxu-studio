import {taskOperation} from './workflow-experience.js?v=88.0';

// Describes the existing execution branches; does not change their inputs or parameters.
const dualReference={
  title:'单图 / 双图对比',
  help:'一次生成两张：仅用原图，以及原图＋补充参考图。',
  slots:{'76':{label:'原图',help:'两份结果都使用'},'81':{label:'补充参考图',help:'仅双图结果使用'}}
};
export const workflowPresentation={
  'local-card-80':{title:'动漫角色套图',help:'一份创作要求，按套图数量自动补全不同构图。',slots:{'84':{label:'人物参考图',help:'套图共用的人物与风格参考'}}},
  'local-card-81':{title:'真人写真套图',help:'一份创作要求，按套图数量自动补全不同姿势与构图。',slots:{'295':{label:'人物参考图',help:'套图共用的人物与服装参考'}}},
  'local-card-87':{title:'深度约束转漫画',help:'从原图提取深度结构控制漫画构图，深度图是中间参考。',slots:{'701':{label:'原图（提取深度结构）',help:'保留空间结构，重绘漫画风格'}}},
  'local-card-88':{title:'线稿约束转漫画',help:'从原图提取边缘线稿，控制漫画的轮廓与构图。',slots:{'91':{label:'原图（提取边缘线稿）',help:'保留画面轮廓，重绘漫画风格'}}},
  'local-card-11':{title:'Flux 9B / Qwen 模型对比',help:'两种模型使用相同的两张参考图，各生成一张。',slots:{'63':{label:'原图',help:'两种模型共用'},'64':{label:'补充参考图',help:'两种模型共用'}}},
  'local-card-17':dualReference,
  'local-card-18':dualReference,
  'local-card-20':{title:'参考图编辑',help:'上传一张参考图，按描述生成一张修改结果。'}
};
export function workflowHelp(w){return w?.interface?.purpose||workflowPresentation[w?.id]?.help||w?.desc||'';}
export function workflowTitle(w){return workflowPresentation[w?.id]?.title||taskOperation(w).title;}
export function workflowOutputLabel(workflowId,label){
  if(['local-card-17','local-card-18'].includes(workflowId)){
    if(label==='单图结果')return '单图结果 · 仅用原图';
    if(label==='双图结果')return '双图结果 · 原图＋补充参考图';
  }
  return label||'';
}
