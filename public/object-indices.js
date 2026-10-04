import {esc} from './data.js';

export function normalizeObjectIndices(raw){
 const value=String(raw??'').trim();
 if(!value)return '';
 if(!/^[0-9]+(?:\s*,\s*[0-9]+)*$/.test(value))throw new Error('对象编号需填写非负整数，用英文逗号分隔，例如 0,2；留空处理全部对象。');
 return value.replace(/\s+/g,'');
}
export function indicesControl(field,value,id){
 return `<div class="catalog-field catalog-indices-field"><label for="${id}">${esc(field.label||'选择对象')}</label><input type="text" id="${id}" data-catalog-field="${esc(field.id)}" value="${esc(value??'')}" placeholder="全部对象；或填写 0,2" spellcheck="false" autocomplete="off" pattern="\\s*(?:[0-9]+(?:\\s*,\\s*[0-9]+)*)?\\s*" title="非负整数以英文逗号分隔；留空处理全部对象。"><small class="catalog-field-help" title="${esc(field.help||'留空处理全部；编号以检测结果为准。')}">${esc(field.help||'留空处理全部；编号以检测结果为准。')}</small></div>`;
}
