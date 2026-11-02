'use strict';
const experiment = {token:null,run:null,profile:null,note:'',loading:0,spikes:null};
const wfIds = ['kind','x','y','group','replicate','error','title','x-label','y-label','x-min','x-max','y-min','y-max','exclude-rows','exclude-reason','goal','spike-threshold'];
function workflowBusy(busy) {
  document.querySelectorAll('#workflow-panel button,#workflow-panel input,#workflow-panel select,#workflow-panel textarea').forEach(el=>el.disabled=busy);
  $('wf-render').disabled=busy || !experiment.token;
  $('wf-export').disabled=busy || !experiment.run;
  $('wf-preview').disabled=$('wf-ai').disabled=$('wf-spikes').disabled=busy || !state.dataset || !experiment.profile;
  $('wf-use-spikes').disabled=busy || !experiment.spikes?.records.length;
}
function invalidateWorkflow() {
  experiment.token=null;experiment.run=null;
  $('wf-render').disabled=true;$('wf-export').disabled=true;
  $('wf-review').hidden=true;
  $('wf-phase').textContent=state.dataset?'2 · 核对方案与筛选条件':'1 · 导入实验数据';
}
function workflowParams() {
  const result={ai_note:experiment.note};
  for(const id of wfIds)result[id.replaceAll('-','_')]=$('wf-'+id).value.trim();
  return result;
}
function applyWorkflowPlan(plan) {
  for(const id of ['kind','x','y','group','replicate','error'])$('wf-'+id).value=plan[id]||'';
  experiment.note=plan.summary||'';$('wf-suggestion').textContent=experiment.note;
  invalidateWorkflow();updateWorkflowLabels();
}
function updateWorkflowLabels() {
  const time=$('wf-kind').value==='time';
  $('wf-group').disabled=!time || state.busy;
  $('wf-x-min').disabled=$('wf-x-max').disabled=!time || state.busy;
  if(!time){$('wf-group').value='';$('wf-x-min').value='';$('wf-x-max').value='';}
  $('wf-x-caption').textContent=time?'时间 / 数值横轴':'分类 / 浓度横轴';
}
function wfTable(headers,rows) {
  const table=document.createElement('table'),thead=document.createElement('thead'),tr=document.createElement('tr');
  for(const header of headers){const th=document.createElement('th');th.textContent=header;tr.append(th);}thead.append(tr);table.append(thead);
  const body=document.createElement('tbody');
  for(const row of rows){const tr=document.createElement('tr');for(const value of row){const td=document.createElement('td');td.textContent=value===null||value===undefined?'—':String(value);tr.append(td);}body.append(tr);}table.append(body);return table;
}
async function refreshWorkflow() {
  const version=++experiment.loading;experiment.profile=null;experiment.note='';clearSpikeCandidates();invalidateWorkflow();
  for(const id of ['title','x-label','y-label','x-min','x-max','y-min','y-max','exclude-rows','exclude-reason','goal'])$('wf-'+id).value='';
  $('wf-source-preview').replaceChildren();$('wf-suggestion').textContent='正在本地检查列与数据质量…';
  const result=await call('workflow_profile');if(version!==experiment.loading || result.error)return;
  experiment.profile=result;
  for(const id of ['x','group','replicate'])$('wf-'+id).replaceChildren(...(id==='x'?[]:[new Option('不指定','')]),...result.headers.map(c=>new Option(c,c)));
  $('wf-y').replaceChildren(...state.dataset.numeric.map(c=>new Option(c,c)));
  $('wf-source-preview').append(wfTable(['记录号',...result.headers],result.preview.map(r=>[r.record,...r.values])));
  $('wf-source-note').textContent=result.preview_note+' 原文件只读。记录号从表头后的第 1 条数据开始。';
  const missing=result.profile.columns.filter(c=>c.missing).map(c=>`${c.name}: ${c.missing}`);
  $('wf-quality').textContent=`${result.profile.rows} 条记录 · 完全重复记录 ${result.profile.exact_duplicate_rows} 条（保留，等待核查）`+(missing.length?' · 空值 '+missing.join('，'):' · 没有空单元格');
  applyWorkflowPlan(result.plan);workflowBusy(state.busy);updateWorkflowLabels();
}
async function demoWorkflow(kind) {
  if(state.busy)return;
  setBusy(true);status('正在载入合成实验数据…');
  try{const data=await call('demo_workflow',{kind});if(!data.error){adoptDataset(data);status('合成演示数据已载入 · 不代表真实实验结果');}}
  finally{setBusy(false);}
}
async function suggestWorkflow() {
  if(state.busy || !state.dataset)return;
  if(!state.connected || state.dirty || !state.model){showPage('settings');return toast('请先连接模型；本地方案与绘图可直接使用。');}
  setBusy(true);status('AI 正在建议实验分析方案…');
  try{
    const result=await call('workflow_suggest',{model:state.model,goal:$('wf-goal').value.trim()});
    if(!result.error){applyWorkflowPlan(result);status('AI 方案已返回 · 核对后预览筛选');}
  } finally{setBusy(false);updateWorkflowLabels();await refreshBilling();}
}
function numberText(v){return v===null?'—':typeof v==='number'?Number(v.toPrecision(7)).toString():String(v);}
async function previewWorkflow() {
  if(state.busy || !state.dataset)return;
  invalidateWorkflow();setBusy(true);status('正在本地预览筛选与分组统计…');
  try{
    const result=await call('workflow_review',workflowParams());if(result.error)return;
    experiment.token=result.token;
    $('wf-review').hidden=false;
    $('wf-counts').textContent=`共 ${result.total} 条 · 保留 ${result.used} 条 · 排除 ${result.excluded} 条`;
    $('wf-warnings').textContent=result.warnings.join('\n');
    $('wf-decisions').replaceChildren();
    if(result.decisions.length)$('wf-decisions').append(wfTable(['排除记录号','原因'],result.decisions.map(d=>[d.record,d.reasons.join('；')])));
    else $('wf-decisions').textContent='没有排除记录。';
    const flagged=result.flagged;
    $('wf-flags').replaceChildren();
    if(flagged.length)$('wf-flags').append(wfTable(['保留但需核查','提示'],flagged.map(d=>[d.record,d.flags.join('；')])));
    else $('wf-flags').textContent='没有检测到重复记录或可提示的 IQR 离群候选；这不等于数据质量已验证。';
    $('wf-review-note').textContent=result.note+(result.excluded_truncated||result.flagged_truncated?' 页面仅展示各前 200 条，导出包含完整决策。':'');
    $('wf-summary').replaceChildren(wfTable(['曲线 / 组','横轴','n','均值','SD','SEM'],result.summary.map(s=>[s.group,s.x,s.n,numberText(s.mean),numberText(s.sd),numberText(s.sem)])));
    $('wf-summary-note').textContent=result.summary_truncated?'仅展示前 150 个汇总点，导出包含全部。':'';
    $('wf-phase').textContent='3 · 查看筛选影响，确认后生成图';status('筛选预览已就绪 · 尚未生成图表');
  } finally{setBusy(false);updateWorkflowLabels();}
}
async function renderWorkflow() {
  if(state.busy || !experiment.token)return;
  setBusy(true);status('正在本地生成科研图…');
  try{
    const result=await call('workflow_render',{token:experiment.token});if(result.error)return;
    experiment.run=result.run_id;state.charts=result.before?[{...result.before,label:'排除前（同范围）'},{...result,label:'排除后'}]:[result];renderChart(state.charts.length-1);
    $('wf-phase').textContent='4 · 图表已生成，可导出完整结果';status('图表已生成 · 尚未保存文件');
    $('plot-view').scrollIntoView({behavior:'smooth',block:'nearest'});
  }finally{setBusy(false);updateWorkflowLabels();}
}
async function exportWorkflow() {
  if(state.busy || !experiment.run)return;
  setBusy(true);
  try{const result=await call('workflow_export',{run_id:experiment.run});if(!result.error){toast('已创建新结果包：\n'+result.path);status('结果包已保存 · 含 PNG、SVG、统计与完整筛选记录');}}
  finally{setBusy(false);updateWorkflowLabels();}
}
for(const id of wfIds)$('wf-'+id).addEventListener('input',()=>{invalidateWorkflow();clearSpikeCandidates();updateWorkflowLabels();});
$('wf-demo-time').onclick=()=>demoWorkflow('time');$('wf-demo-group').onclick=()=>demoWorkflow('group');
$('wf-local').onclick=()=>{if(experiment.profile)applyWorkflowPlan(experiment.profile.plan);};
$('wf-ai').onclick=suggestWorkflow;$('wf-preview').onclick=previewWorkflow;$('wf-render').onclick=renderWorkflow;$('wf-export').onclick=exportWorkflow;
function clearSpikeCandidates(){experiment.spikes=null;$('wf-spike-results').hidden=true;$('wf-use-spikes').disabled=true;}
async function inspectSpikes(){
  if(state.busy || !state.dataset)return;
  setBusy(true);status('正在按单孔时间曲线检查孤立跳点…');
  try{
    const result=await call('workflow_spikes',workflowParams());if(result.error)return;
    experiment.spikes=result;$('wf-spike-results').hidden=false;
    $('wf-spike-rule').textContent=result.rule;
    $('wf-spike-table').replaceChildren(wfTable(['记录号','曲线/孔','原始单元格','时间','读数','偏离倍数'],result.candidates.map(c=>[c.record,c.replicate,c.source_cell,numberText(c.x),numberText(c.y),numberText(c.score)])));
    $('wf-spike-note').textContent=`找到 ${result.total} 个候选；跳过 ${result.skipped_series} 条不满足条件的曲线。`+result.note+(result.truncated?' 页面仅显示前200个候选。':'');
    status('孤立跳点检查完成 · 尚未排除任何点');
  }finally{setBusy(false);updateWorkflowLabels();}
}
function useSpikeCandidates(){
  const checked=experiment.spikes;if(!checked?.records.length)return;
  const existing=$('wf-exclude-rows').value.trim();$('wf-exclude-rows').value=[existing,checked.records.join(',')].filter(Boolean).join(',');
  $('wf-exclude-reason').value=($('wf-exclude-reason').value+' 探索性试排除孤立跳点候选（未确认仪器故障）：'+checked.rule).trim().slice(0,1000);
  invalidateWorkflow();toast('已填入候选记录号及规则；请预览筛选后生成，比较排除前后。');
}
$('wf-spikes').onclick=inspectSpikes;$('wf-use-spikes').onclick=useSpikeCandidates;
workflowBusy(false);
