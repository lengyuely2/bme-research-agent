'use strict';
const $ = id => document.getElementById(id);
const state = { page: 'chat', sessions: [], active: null, connected: false, dirty: false,
  models: [], model: '', library: null, dataset: null, useDataset: false, evidence: [],
  selected: new Set(), charts: [], chartIndex: 0, preview: null, busy: false, streaming: '', monitorFiles: [], toastTimer: null, sourceContext:null };
const titles = { chat: '新任务', library: '本地资料', analysis: '数据分析与绘图', monitor: '图片监控', settings: '设置' };
const prompts = {
  experiment: '请围绕生物传感与疾病检测，帮我梳理实验目标、传感原理、操作步骤、关键条件、对照设置和结果判定。请先确认缺失信息。',
  troubleshoot: '我在生物传感或疾病检测实验中遇到问题。请先询问目标物、传感器类型、实验步骤、异常表现和已有对照，再分析可能原因，并提出优先验证步骤和可能的解决方案。',
  paper: '请精读本次附上的论文：先说明读到了哪些文件与页面，然后依次整理研究目的、识别元件和传感原理、实验流程与关键参数表、对照与重复设计、检测性能、逐图解释、局限与可复现性。每项关键结论标注来源页码；未报告的参数明确写原文未报告，区分作者结果、你的观察与改进建议。',
};

function escapeText(value) { return String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function markdown(text) {
  // Only escaped text is formatted. No images, external links, raw HTML, or executable content.
  let code = false, html = '', list = false;
  for (const raw of text.split('\n')) {
    if (raw.startsWith('```')) { if (list) { html += '</ul>'; list = false; } code = !code; html += code ? '<pre><code>' : '</code></pre>'; continue; }
    if (code) { html += escapeText(raw) + '\n'; continue; }
    const line = escapeText(raw).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\[(S\d{3}-(?:C\d{4}|P\d{3}))\]/g, '<button class="citation" data-citation="$1" title="查看原文来源">[$1]</button>');
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (bullet) { if (!list) { html += '<ul>'; list = true; } html += `<li>${bullet[1]}</li>`; continue; }
    if (list) { html += '</ul>'; list = false; }
    if (heading) html += `<h${heading[1].length}>${heading[2]}</h${heading[1].length}>`;
    else if (line.trim()) html += `<p>${line}</p>`;
  }
  if (list) html += '</ul>';
  if (code) html += '</code></pre>';
  return html;
}

function toast(message, error = false) {
  clearTimeout(state.toastTimer); $('toast').textContent = message; $('toast').className = 'toast' + (error ? ' error' : ''); $('toast').hidden = false;
  state.toastTimer = setTimeout(() => $('toast').hidden = true, error ? 9500 : 5000);
}
function status(message) { $('global-status').textContent = message; }
function renderBilling(data) {
  const amount = data.balance === null ? null : Number(data.balance).toLocaleString('en-US', {minimumFractionDigits:2,maximumFractionDigits:6});
  $('header-balance').textContent = amount === null ? '余额与用量' : '$' + amount + (data.needs_confirmation ? ' · 待核对' : ' · 已核对');
  $('billing-amount').textContent = amount === null ? '尚未同步' : '$' + amount;
  $('billing-time').textContent = data.confirmed_at ? '核对时间：' + data.confirmed_at.replace('T',' ').replace(/\.\d+\+00:00$/, ' UTC') : '从官方账单页核对后，在下方填写。';
  $('billing-state').textContent = data.balance === null ? '未记录余额，不代表余额为零。' : data.needs_confirmation ? `核对后又发起了 ${data.requests_since_confirmation} 次请求，余额需要重新核对。` : '这是你手动核对的余额记录，其他软件消费或额度到期仍可能改变实际余额。';
  $('billing-input').textContent = data.input_tokens.toLocaleString();
  $('billing-output').textContent = data.output_tokens.toLocaleString();
  $('billing-requests').textContent = data.requests.toLocaleString();
  $('billing-usage-note').textContent = `本次启动统计；${data.reported_requests} 次请求返回用量，${data.requests_without_usage} 次未取得用量。未返回部分可能产生费用；其他软件的使用不在此统计内。`;
  $('balance-confirm').disabled = !state.connected || state.dirty;
}
async function refreshBilling() { const data = await call('billing', {}, true); if (!data.error) renderBilling(data); }
async function showBilling() { if (state.busy) return toast('请在当前请求结束后查看余额与用量。'); await refreshBilling(); $('billing-dialog').showModal(); }
function errorText(error) {
  const fields = [error.status ? 'HTTP ' + error.status : '', error.code ? '代码：' + error.code : '',
    error.exception ? '类型：' + error.exception : '', error.request_id ? '请求 ID：' + error.request_id : ''].filter(Boolean);
  return (error.message || '操作没有完成。') + (fields.length ? '\n' + fields.join(' · ') : '');
}
async function call(operation, params = {}, quiet = false) {
  try {
    const result = await window.bme.invoke(operation, params);
    if (!result.ok) {
      const error = result.error || { message: '操作没有完成。' };
      if (!quiet) toast(errorText(error), true);
      return { error: {...error, message:errorText(error)} };
    }
    return result.data;
  } catch { if (!quiet) toast('桌面服务连接中断，请重新启动应用。', true); return { error: { message: '本地服务不可用。' } }; }
}

function showPage(page) {
  state.page = page;
  document.querySelectorAll('.page').forEach(el => el.classList.toggle('active', el.id === 'page-' + page));
  document.querySelectorAll('.primary-nav [data-page]').forEach(el => el.classList.toggle('active', el.dataset.page === page));
  $('page-name').textContent = page === 'chat' ? activeSession().title : titles[page];
}
function activeSession() { return state.sessions.find(x => x.id === state.active); }
function newSession() {
  if (state.busy) return toast('请先停止或等待当前任务。');
  const item = { id: crypto.randomUUID(), title: '新任务', messages: [], attachments:[] };
  state.sessions.unshift(item); state.active = item.id; $('question').value = ''; state.useDataset = false; state.selected.clear();
  state.preview = null; if ($('preview-dialog').open) $('preview-dialog').close();
  $('dataset-chip').hidden = true; renderSessions(); renderMessages(); renderAttachments(); showPage('chat');
}
function renderSessions() {
  $('session-list').replaceChildren(); $('session-count').textContent = state.sessions.length;
  if (state.page === 'chat') $('page-name').textContent = activeSession().title;
  for (const item of state.sessions) {
    const button = document.createElement('button'); button.className = 'session-row' + (item.id === state.active ? ' active' : '');
    button.textContent = item.title; button.title = item.title;
    button.onclick = () => { if (state.busy) return toast('当前任务仍在进行。'); state.active = item.id; state.streaming = ''; state.useDataset=false; state.selected.clear(); $('dataset-chip').hidden=true; renderSessions(); renderMessages(); renderAttachments(); showPage('chat'); };
    $('session-list').append(button);
  }
}
function messageElement(item) {
  const element = document.createElement('article'); element.className = 'message ' + item.role;
  if (item.role === 'assistant') {
    element.dataset.reportId = item.reportId || '';
    element.innerHTML = markdown(item.text);
    const tools = document.createElement('div'); tools.className = 'message-tools';
    const copy = document.createElement('button'); copy.innerHTML = '<svg><use href="#i-copy"/></svg>复制';
    copy.onclick = async () => { const copied = await call('copy_text', { text: item.text }); if (!copied.error) toast('已复制回答。'); };
    const save = document.createElement('button'); save.innerHTML = '<svg><use href="#i-download"/></svg>保存报告';
    save.onclick = async () => { const data = await call('save_report', { report_id: item.reportId }); if (!data.error) toast('已创建新报告：\n' + data.path); };
    tools.append(copy, save);
    if (item.note) { const note = document.createElement('span'); note.textContent = item.note; tools.append(note); }
    element.append(tools);
    const sources = document.createElement('div'); sources.className='message-sources';
    const references = [...(item.attachments||[]).map(a=>({id:a.kind==='pdf'?a.source_id+'-P001':(item.sources||[]).find(e=>e.id.startsWith(a.source_id+'-'))?.id,source:a.name,location:a.kind==='pdf'?'PDF 全文':'附件'})).filter(source=>source.id),...(item.sources||[])];
    const seen = new Set();
    for (const source of references) {
      const key=source.id.slice(0,4);if (seen.has(key) || seen.size>=4) continue; seen.add(key);
      const link=document.createElement('button'); link.textContent=source.source; link.title=source.location;
      link.onclick=()=>viewReportSource(item.reportId,source.id); sources.append(link);
    }
    if (seen.size) element.append(sources);
    element.addEventListener('click',event=>{const link=event.target.closest('[data-citation]'); if(link) viewReportSource(item.reportId,link.dataset.citation);});
  } else element.textContent = item.text;
  if (item.role === 'user' && item.attachments?.length) {
    const files=document.createElement('div');files.className='message-file-names';files.textContent=item.attachments.map(a=>a.name).join(' · ');element.append(files);
  }
  return element;
}
function renderMessages() {
  const messages = activeSession().messages; $('message-list').replaceChildren(...messages.map(messageElement));
  const empty = messages.length === 0 && !state.busy;
  $('chat-stage').classList.toggle('empty', empty); $('welcome').hidden = !empty; $('suggestions').hidden = !empty;
  $('conversation-scroll').hidden = empty;
  if (state.streaming) {
    const streaming = document.createElement('article'); streaming.className = 'message assistant streaming'; streaming.id = 'streaming-answer';
    streaming.innerHTML = markdown(state.streaming); $('message-list').append(streaming);
  }
  requestAnimationFrame(() => $('conversation-scroll').scrollTop = $('conversation-scroll').scrollHeight);
}
function setBusy(active) {
  state.busy = active; $('send').disabled = active; $('stop').hidden = !active;
  for (const id of ['approve', 'plot', 'choose-data', 'demo-data', 'load-models', 'test-model','attach','demo-attachments']) $(id).disabled = active;
  document.querySelectorAll('#attachment-list button,#attachment-list select').forEach(el=>el.disabled=active);
  if(typeof workflowBusy==='function')workflowBusy(active);
}
function selectedModel() { return state.model; }
function packetParams() {
  const history = activeSession().messages.filter(x => ['user', 'assistant'].includes(x.role)).slice(-4).map(x => ({ role: x.role, text: x.text.slice(0, 3500) }));
  return { question: $('question').value.trim(), mode: $('chat-mode').value, model: selectedModel(),
    use_dataset: state.useDataset, evidence_ids: [...state.selected], history,
    attachment_ids:activeSession().attachments.map(a=>a.id) };
}

async function prepare(previewOnly = false) {
  if (state.busy) return;
  if (!$('question').value.trim()) { $('question').focus(); return; }
  if (!state.connected || !state.model || state.dirty) { showPage('settings'); toast('请先加载账户可用模型并选择一个模型。'); return; }
  setBusy(true); status('正在整理本次资料包…');
  const params = packetParams(); const result = await call('prepare', params);
  setBusy(false);
  if (result.error) { status('发送准备未完成'); return; }
  state.preview = { ...result, question: params.question, attachments:[...activeSession().attachments] };
  if (!previewOnly) return approve();
  $('preview-meta').textContent = `${result.model}  ·  api.openai.com  ·  ${result.evidence_count} 个证据片段 · ${activeSession().attachments.length} 个附件`;
  $('preview-content').textContent = result.preview;
  $('preview-tools').textContent = result.instructions + '\n\n' + JSON.stringify(result.tools, null, 2);
  $('preview-dialog').showModal(); status('正在查看发送内容');
}
async function approve() {
  if (!state.preview || state.busy) return;
  const preview = state.preview; state.preview = null;
  if ($('preview-dialog').open) $('preview-dialog').close();
  const session = activeSession(); session.messages.push({ role: 'user', text: preview.question, attachments:preview.attachments });
  if (session.title === '新任务') session.title = preview.question.slice(0, 24);
  $('question').value = ''; state.streaming = ''; setBusy(true); renderSessions(); renderMessages(); status('正在请求模型…');
  const result = await call('approve', { token: preview.token }, true);
  setBusy(false); state.streaming = '';
  if (result.error) {
    session.messages.push({ role: 'error', text: result.error.message });
    status('请求未完成');
    if (['model_not_found', 'authentication', 'permission'].includes(result.error.kind)) {
      $('connection-result').textContent = result.error.message; $('connection-result').className = 'connection-result error';
    }
  } else {
    session.messages.push({ role: 'assistant', text: result.answer, reportId: result.report_id,
      sources:result.sources||[],attachments:result.attachments||[],
      note: result.citation_issues.length ? '引用需要复核' : `${result.tokens.input + result.tokens.output} tokens` });
    status(result.warning || '回答完成 · 报告与图表等待手动保存');
    if (result.charts.length) { state.charts = result.charts; renderChart(result.charts.length - 1); }
    if (result.warning) toast(result.warning);
  }
  renderMessages();
  await refreshBilling();
}
async function connect() {
  const key = $('api-key').value.trim(); if (!key) return toast('请粘贴 API Key。');
  setBusy(true); $('connection-result').textContent = '正在验证密钥并加载账户模型…'; $('connection-result').className = 'connection-result';
  const data = await call('connect', { api_key: key }, true); setBusy(false);
  if (data.error) {
    state.connected = false; state.models = []; state.model = '';
    $('model-select').replaceChildren(new Option('连接失败，请检查下方原因', ''));
    $('connection-result').textContent = data.error.message;
    $('connection-result').className = 'connection-result error';
  } else {
    state.connected = true; state.dirty = false; state.models = data.models;
    $('model-select').replaceChildren(new Option('选择一个账户可用模型', ''), ...data.models.map(name => new Option(name, name)));
    state.model = '';
    $('connection-result').textContent = `密钥有效，已加载 ${data.models.length} 个文本模型。请选择模型，再发送一条测试请求。`;
    $('connection-result').className = 'connection-result success';
    // Clear the visible input; the backend retains the key only in memory.
    $('api-key').value = ''; $('api-key').placeholder = '密钥已验证（仅本次会话）';
  }
  updateConnection();
  await refreshBilling();
}
function updateConnection() {
  $('balance-confirm').disabled = !state.connected || state.dirty;
  $('connection-dot').classList.toggle('connected', state.connected && !state.dirty);
  $('composer-model').replaceChildren(document.createTextNode(state.model || '选择模型'));
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'), use = document.createElementNS(svg.namespaceURI, 'use');
  use.setAttribute('href', '#i-chevron'); svg.append(use); $('composer-model').append(svg);
  $('model-options').replaceChildren();
  state.models.forEach(name => {
    const button = document.createElement('button'); button.className = 'model-option' + (name === state.model ? ' selected' : ''); button.textContent = name;
    button.onclick = () => { state.model = name; $('model-select').value = name; $('model-popover').hidden = true; updateConnection(); };
    $('model-options').append(button);
  });
}

async function loadLibrary(demo = false) {
  status('正在本地读取资料…'); const data = await call(demo ? 'demo_library' : 'choose_library');
  if (data.error || data.cancelled) return;
  state.library = data; state.selected.clear(); $('project-name').textContent = data.name;
  $('library-summary').replaceChildren();
  const title = document.createElement('strong'); title.textContent = `${data.name}  ·  ${data.files.length} 个文件  ·  ${data.chunks} 个片段`;
  const path = document.createElement('div'); path.textContent = data.path; path.className = 'path-display';
  const tags = document.createElement('div'); tags.className = 'file-names';
  for (const name of data.files) { const tag = document.createElement('span'); tag.className = 'file-tag'; tag.textContent = name; tags.append(tag); }
  $('library-summary').append(title, path, tags);
  if (data.warnings.length) { const note = document.createElement('p'); note.textContent = data.warnings.join('\n'); $('library-summary').append(note); }
  status('资料已载入 · 未发送到云端'); showPage('library');
}
async function search() {
  const data = await call('search', { query: $('search-query').value }); if (data.error) return;
  state.evidence = data.items; $('evidence-list').replaceChildren();
  for (const item of data.items) {
    const card = document.createElement('article'); card.className = 'evidence-card';
    const header = document.createElement('div'); header.className = 'evidence-header';
    const check = document.createElement('input'); check.type = 'checkbox'; check.checked = state.selected.has(item.id);
    check.onchange = () => { if (check.checked && state.selected.size >= 8) { check.checked = false; return toast('每次最多选择 8 项证据。'); } check.checked ? state.selected.add(item.id) : state.selected.delete(item.id); $('evidence-selected').textContent = `已选择 ${state.selected.size} 项证据`; };
    const id = document.createElement('span'); id.className = 'evidence-id'; id.textContent = item.id;
    const source = document.createElement('span'); source.textContent = item.source;
    const location = document.createElement('span'); location.className = 'evidence-location'; location.textContent = item.location;
    const text = document.createElement('p'); text.textContent = item.text;
    header.append(check, id, source, location); card.append(header, text); $('evidence-list').append(card);
  }
  if (!data.items.length) $('evidence-list').innerHTML = '<div class="empty-state">没有找到相关片段，请调整检索词。</div>';
  status(`本地找到 ${data.count} 个相关片段`);
}
async function loadData(demo = false) {
  const data = await call(demo ? 'demo_data' : 'choose_dataset'); if (data.error || data.cancelled) return;
  adoptDataset(data);
}
function adoptDataset(data) {
  state.dataset = data; state.charts = [];
  $('data-summary').textContent = `${data.name}${data.sheet?' / '+data.sheet:''}  ·  ${data.rows} 行  ·  ${data.headers.length} 列  ·  ${data.numeric.length} 个数值列`;
  $('plot-x').replaceChildren(new Option('行号', '行号'), ...data.numeric.map(name => new Option(name, name)));
  $('plot-y').replaceChildren(...data.numeric.map(name => new Option(name, name)));
  if (data.numeric.length > 1) { $('plot-x').value = data.numeric[0]; $('plot-y').value = data.numeric[1]; }
  $('plot-view').innerHTML = '<div class="empty-state"><strong>数据已载入</strong><span>选择横轴、纵轴与图形，生成图表。</span></div>';
  $('chart-gallery').hidden = true; status('实验数据已载入 · 原始文件未修改'); showPage('analysis');
  if(data.warnings?.length) toast(data.warnings.join('\n'));
  if(typeof refreshWorkflow==='function')refreshWorkflow();
}
function renderChart(index) {
  state.chartIndex = index; const chart = state.charts[index]; if (!chart) return;
  const image = document.createElement('img'); image.alt = '实验数据图表'; if (chart.image.startsWith('data:image/png;base64,')) image.src = chart.image;
  $('plot-view').replaceChildren(image); $('plot-note').textContent = chart.note;
  $('chart-gallery').replaceChildren(); $('chart-gallery').hidden = state.charts.length < 2;
  state.charts.forEach((_item, i) => { const b = document.createElement('button'); b.textContent = _item.label || `图表 ${i + 1}`; b.classList.toggle('active', index === i); b.onclick = () => renderChart(i); $('chart-gallery').append(b); });
}
function renderMonitorFiles(files) {
  state.monitorFiles = files; $('image-list').replaceChildren();
  files.forEach(name => {
    const button = document.createElement('button'); button.className = 'image-file'; button.textContent = name; button.title = name;
    button.onclick = async () => { const data = await call('preview_image', { name }); if (!data.error) showImage(data); };
    $('image-list').append(button);
  });
  if (!files.length) $('image-list').innerHTML = '<div class="empty-state">文件夹中尚无可预览图片。</div>';
}
function showImage(data) {
  const image = document.createElement('img'); image.alt = data.name;
  if (data.image.startsWith('data:image/png;base64,')) image.src = data.image;
  $('image-view').replaceChildren(image);
  $('image-details').textContent = `${data.name}  ·  ${data.info.width} × ${data.info.height}  ·  ${data.info.mode}  ·  ${data.info.frames} 帧（预览首帧） · 未上传`;
}
async function monitor(operation) {
  const data = await call(operation); if (data.error || data.cancelled) return;
  if (data.path) $('monitor-path').textContent = data.path;
  if (data.files) renderMonitorFiles(data.files);
  $('monitor-status').textContent = data.running ? '监控中' : '已暂停'; $('monitor-status').classList.toggle('running', !!data.running);
  status(data.running ? '本地图片监控已启动 · 不自动上传' : '图片监控已暂停');
}

function renderAttachments() {
  const files=activeSession().attachments;
  $('attachment-list').replaceChildren(); $('attachment-list').hidden=files.length===0;
  for(const file of files) {
    const card=document.createElement('div');card.className='attachment-card';
    const open=document.createElement('button');open.className='attachment-open';
    const name=document.createElement('strong');name.textContent=file.name;
    const description=document.createElement('span');description.textContent=(file.kind==='pdf'?file.pages+' 页 · ':'')+file.transmission;
    open.append(name,description);open.title=[...file.notes,'点击在本地预览；发送消息时才交给模型。'].join('\n');
    open.onclick=()=>viewAttachment(file.id,1);card.append(open);
    if(file.sheets?.length>1) {
      const select=document.createElement('select');select.title='选择本次使用的工作表';
      select.replaceChildren(...file.sheets.map(sheet=>new Option(sheet,sheet)));select.value=file.sheet;
      select.onchange=async()=>{setBusy(true);const result=await call('attachment_sheet',{id:file.id,sheet:select.value});setBusy(false);
        if(!result.error) activeSession().attachments=activeSession().attachments.map(item=>item.id===file.id?result:item);renderAttachments();};
      card.append(select);
    }
    if(file.can_plot) {
      const plot=document.createElement('button');plot.className='attachment-action';plot.textContent='绘图';
      plot.onclick=async()=>{const data=await call('attachment_data',{id:file.id});if(!data.error)adoptDataset(data);};card.append(plot);
    }
    const remove=document.createElement('button');remove.className='attachment-remove';remove.textContent='×';remove.title='移除对话附件，不删除原文件';
    remove.onclick=async()=>{const result=await call('remove_attachment',{id:file.id});if(!result.error){activeSession().attachments=files.filter(item=>item.id!==file.id);renderAttachments();}};
    card.append(remove);$('attachment-list').append(card);
  }
}
async function addAttachments(files=null,demo=false) {
  if(state.busy)return toast('请等待当前操作完成。');
  const remaining=4-activeSession().attachments.length;
  if(remaining<1)return toast('当前任务最多关联 4 个附件，可先移除不需要的附件。');
  if(files && files.length>remaining)return toast('当前任务还可以添加 '+remaining+' 个附件。');
  setBusy(true);status('正在本地读取附件…');
  let data;
  try {
    if(files){const result=await window.bme.importFiles(files);data=result.ok?result.data:{error:result.error};}
    else data=await call(demo?'demo_attachments':'choose_attachments',{remaining});
    if(data.error){toast(data.error.message||'附件未能添加。',true);return;}
    if(data.cancelled)return;
    const accepted=data.items.slice(0,remaining);
    for(const extra of data.items.slice(remaining))await call('remove_attachment',{id:extra.id},true);
    activeSession().attachments.push(...accepted);
    if(accepted.length){$('chat-mode').value='auto';showPage('chat');renderAttachments();status('附件已在本地就绪 · 随本任务后续问题发送');}
    if(data.warnings?.length)toast(data.warnings.join('\n'),true);
  } catch {toast('无法添加附件，请重新选择文件。',true);}
  finally{setBusy(false);}
}
async function viewAttachment(id,page=1) {
  if(state.busy)return toast('请等待当前操作完成后查看附件。');
  const data=await call('attachment_preview',{id,page});if(data.error)return;
  showSource(data,{type:'attachment',id});
}
async function viewReportSource(reportId,citation) {
  if(state.busy)return toast('请等待当前回答完成后查看来源。');
  const data=await call('view_source',{report_id:reportId,citation});if(data.error)return;
  showSource(data,{type:'report',reportId,citation});
}
function showSource(data,context) {
  state.sourceContext={...context,page:data.page,pages:data.pages};
  $('source-name').textContent=data.name;
  $('source-location').textContent=(data.location||'第 '+data.page+' / '+data.pages+' 页')+(data.citation?' · ['+data.citation+']':'');
  $('source-page').value=data.page;$('source-page').max=data.pages;
  $('source-prev').disabled=data.page<=1;$('source-next').disabled=data.page>=data.pages;
  $('source-pagination').hidden=data.pages<=1;
  $('source-image').hidden=!data.image;$('source-image').removeAttribute('src');
  if(data.image?.startsWith('data:image/png;base64,'))$('source-image').src=data.image;
  $('source-text').textContent=data.text||'此页无可提取文字，可结合上方页面图像查看。';
  $('source-text-details').open=!data.image;
  if(!$('source-dialog').open)$('source-dialog').showModal();
  $('source-body').scrollTop=0;
}
function navigateSource(page) {
  const context=state.sourceContext;if(!context || !Number.isInteger(page) || page<1 || page>context.pages)return;
  if(context.type==='attachment')return viewAttachment(context.id,page);
  return viewReportSource(context.reportId,context.citation.slice(0,4)+'-P'+String(page).padStart(3,'0'));
}
document.addEventListener('dragover',event=>{if([...event.dataTransfer.types].includes('Files')){event.preventDefault();event.dataTransfer.dropEffect='copy';document.body.classList.add('dragging-files');}});
document.addEventListener('dragleave',event=>{if(!event.relatedTarget)document.body.classList.remove('dragging-files');});
document.addEventListener('drop',event=>{document.body.classList.remove('dragging-files');if(event.dataTransfer.files.length){event.preventDefault();addAttachments([...event.dataTransfer.files]);}});

document.querySelectorAll('[data-page]').forEach(button => button.onclick = () => showPage(button.dataset.page));
document.querySelectorAll('[data-action="new"]').forEach(button => button.onclick = newSession);
document.querySelectorAll('[data-prompt]').forEach(button => button.onclick = () => { $('question').value = prompts[button.dataset.prompt]; $('question').focus(); });
$('top-new').onclick = newSession; $('sidebar-toggle').onclick = () => document.body.classList.toggle('sidebar-collapsed');
$('header-settings').onclick = $('model-settings').onclick = () => { $('model-popover').hidden = true; showPage('settings'); };
$('composer-model').onclick = () => { if (!state.connected || state.dirty) return showPage('settings'); $('model-popover').hidden = !$('model-popover').hidden; };
document.addEventListener('click', event => { if (!$('model-popover').contains(event.target) && !$('composer-model').contains(event.target)) $('model-popover').hidden = true; });
$('project-add').onclick = $('project-row').onclick = () => loadLibrary();
$('attach').onclick = () => addAttachments();
$('demo-attachments').onclick = () => addAttachments(null,true);
$('close-source').onclick = () => $('source-dialog').close();
$('source-prev').onclick = () => navigateSource(state.sourceContext.page-1);
$('source-next').onclick = () => navigateSource(state.sourceContext.page+1);
$('source-page').onchange = () => navigateSource(Number($('source-page').value));
$('choose-library').onclick = () => loadLibrary(); $('demo-library').onclick = () => loadLibrary(true);
$('send').onclick = () => prepare(); $('approve').onclick = approve;
$('preview-request').onclick = () => prepare(true);
$('close-preview').onclick = () => { $('preview-dialog').close(); state.preview = null; status('已取消本次发送'); };
$('question').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); prepare(); } });
$('stop').onclick = async () => { await call('cancel'); status('正在停止后续请求…'); };
$('load-models').onclick = connect;
$('api-key').addEventListener('input', () => { state.dirty = true; updateConnection(); });
$('model-select').onchange = () => { state.model = $('model-select').value; updateConnection(); };
$('open-keys').onclick = () => call('open_keys');
$('test-model').onclick = async () => { if (!state.model) return toast('请先选择模型。'); setBusy(true); const data = await call('test_model', { model: state.model }, true); setBusy(false); $('connection-result').textContent = data.error?.message || data.message; $('connection-result').className = 'connection-result ' + (data.error ? 'error' : 'success'); await refreshBilling(); };
$('header-balance').onclick = $('settings-balance').onclick = showBilling;
$('close-billing').onclick = () => $('billing-dialog').close();
$('open-billing').onclick = () => call('open_billing');
$('balance-confirm').onclick = async () => {
  const data = await call('set_balance', {amount:$('balance-value').value.trim()});
  if (!data.error) {renderBilling(data); $('balance-value').value = ''; toast('已记录上次核对余额；以官方账单页为准。');}
};
$('copy-diagnostics').onclick = async () => {
  const data = await call('diagnostics'); if (data.error) return;
  const result = await call('copy_text', {text:JSON.stringify(data, null, 2)}); if (result.error) return;
  toast((data.local_check.passed ? '本地 SDK 自检通过。' : '本地 SDK 自检未通过。') + '\n诊断信息已复制，不包含密钥或资料正文。');
};
$('search-evidence').onclick = search; $('search-query').onkeydown = event => { if (event.key === 'Enter') search(); };
$('use-evidence').onclick = () => { $('chat-mode').value = 'evidence'; state.useDataset = false; $('dataset-chip').hidden = true; showPage('chat'); $('question').focus(); toast(state.selected.size ? `已关联 ${state.selected.size} 项证据。` : '发送时将按问题检索资料。'); };
$('local-extract').onclick = async () => { if (!$('question').value.trim()) return toast('请输入要整理的研究问题。'); const params = packetParams(); const data = await call('local_report', params); if (data.error) return; activeSession().messages.push({ role: 'user', text: params.question }, { role: 'assistant', text: data.answer, reportId: data.report_id, note: '完全本地 · 未调用 GPT' }); $('question').value = ''; activeSession().title = params.question.slice(0, 24); renderSessions(); renderMessages(); status('本地摘录已生成，等待手动保存。'); };
$('choose-data').onclick = () => loadData(); $('demo-data').onclick = () => loadData(true);
$('plot').onclick = async () => { if(typeof invalidateWorkflow==='function')invalidateWorkflow(); setBusy(true); status('正在本地绘图…'); const data = await call('plot', { kind: $('plot-kind').value, x: $('plot-x').value, y: $('plot-y').value }); setBusy(false); if (!data.error) { state.charts = [data]; renderChart(0); status('图表已生成 · 未保存'); } };
$('save-chart').onclick = async () => { const data = await call('save_chart', { index: state.chartIndex }); if (!data.error) toast('已创建新图表：\n' + data.path); };
$('show-statistics').onclick = () => { if (!state.dataset) return toast('请先导入数据。'); $('statistics-content').textContent = state.dataset.name + '\n\n' + state.dataset.summary; $('statistics-dialog').showModal(); };
$('close-statistics').onclick = () => $('statistics-dialog').close();
$('analyze-data').onclick = () => { if (!state.dataset) return toast('请先导入数据。'); state.useDataset = true; state.selected.clear(); $('dataset-chip').hidden = false; $('chat-mode').value = 'evidence'; $('question').value = '请分析这份 BME 实验数据的描述统计、采样与测量局限，并按需要调用本地绘图工具生成合适的图表。'; showPage('chat'); $('question').focus(); };
$('clear-dataset').onclick = () => { state.useDataset = false; $('dataset-chip').hidden = true; };
$('choose-monitor').onclick = () => monitor('choose_monitor'); $('resume-monitor').onclick = () => monitor('resume_monitor'); $('pause-monitor').onclick = () => monitor('monitor_stop');
async function chooseOutput() { const data = await call('choose_output'); if (!data.error && !data.cancelled) { $('output-path').textContent = data.path; toast('已更新独立结果目录。'); } }
$('choose-output').onclick = $('header-output').onclick = chooseOutput;
$('sandbox-config').onclick = async () => { const data = await call('sandbox_config', { online: $('sandbox-online').checked }); if (!data.error) toast('已生成沙盒启动配置：\n' + data.path); };
document.addEventListener('keydown', event => { if (event.ctrlKey && event.key.toLowerCase() === 'n') { event.preventDefault(); newSession(); } });

window.bme.onEvent(event => {
  if (event.event === 'progress') status(event.message);
  else if (event.event === 'text') { state.streaming += event.delta; renderMessages(); }
  else if (event.event === 'monitor') { renderMonitorFiles(event.files); $('monitor-status').textContent = `监控中 · ${event.files.length} 张`; if (event.new.length) status('发现新增或更新图片：' + event.new.join('、')); }
  else if (event.event === 'image') showImage(event);
  else if (event.event === 'monitor_warning' || event.event === 'fatal') toast(event.message, true);
  else if (event.event === 'toggle_sidebar') document.body.classList.toggle('sidebar-collapsed');
});
newSession();
call('status').then(data => { if (!data.error) { $('output-path').textContent = data.output; status('本地就绪 · 在设置中连接模型'); } });
refreshBilling();
