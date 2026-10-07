// JSON numbers must retain an exact integer through browser drafts and requests.
// Keep the node schema intact; narrow only the browser's editable projection.
export function browserNumericControl(field){
 if(field.type!=='number'||!field.integer)return field;
 const cap=range=>({...range,...(range.min<Number.MIN_SAFE_INTEGER?{min:Number.MIN_SAFE_INTEGER}:{}),...(range.max>Number.MAX_SAFE_INTEGER?{max:Number.MAX_SAFE_INTEGER}:{})});
 return {...cap(field),...(field.customRange?{customRange:cap(field.customRange)}:{})};
}
export function validateBrowserNumbers(config,draft){
 for(const field of config.controls||[]){
  if(field.type!=='number')continue;
  const value=Number(draft.catalogValues?.[field.id]??field.value);
  if(field.integer&&!Number.isSafeInteger(value))throw new Error(`${field.label}需要填写可准确保存的整数。`);
  const range=field.customRange||field;
  if(!Number.isFinite(value)||(range.min!==undefined&&value<range.min)||(range.max!==undefined&&value>range.max))throw new Error(`请检查${field.label}的范围。`);
 }
}
