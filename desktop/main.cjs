'use strict';
const { app, BrowserWindow, ipcMain, dialog, protocol, session, shell, clipboard } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const readline = require('node:readline');

protocol.registerSchemesAsPrivileged([{ scheme: 'bme', privileges: { standard: true, secure: true, supportFetchAPI: true } }]);
app.setName('BME Workbench');
app.setPath('userData', path.join(app.getPath('appData'), 'BMEWorkbench-v0.5.1'));
if (!app.requestSingleInstanceLock()) app.exit(0);
let win, backend, nextId = 0, monitorPath = null;
const debugStartup = process.argv.includes('--self-test');
const trace = message => { if (debugStartup) process.stderr.write(message + '\n'); };
const pending = new Map();
const root = path.resolve(__dirname, '..');
const installedBackend = path.join(path.dirname(process.execPath), 'backend', 'BMEBackend.exe');
const devPython = path.join(root, '.venv', 'Scripts', 'python.exe');
const publicOperations = new Set(['status', 'connect', 'test_model', 'search', 'prepare', 'approve', 'local_report',
  'demo_library', 'demo_data', 'plot', 'save_chart', 'save_report', 'monitor_stop', 'preview_image', 'cancel', 'diagnostics', 'billing', 'set_balance',
  'remove_attachment','attachment_preview','attachment_sheet','attachment_data','view_source','demo_attachments','workflow_profile','workflow_suggest','workflow_review','workflow_render','workflow_export','demo_workflow','workflow_spikes']);

function request(operation, params = {}) {
  trace('broker request: ' + operation);
  if (!backend || backend.killed) return Promise.resolve({ ok: false, error: { message: '本地分析服务尚未就绪，请重新启动应用。' } });
  const id = ++nextId;
  return new Promise(resolve => {
    const timer = setTimeout(() => {
      pending.delete(id);
      resolve({ ok: false, error: { message: '操作超时。已发送的数据不能撤回，可以停止后重试。' } });
    }, 330000);
    pending.set(id, { resolve, timer });
    backend.stdin.write(JSON.stringify({ id, operation, params }) + '\n');
  });
}

function startBackend() {
  const packaged = fs.existsSync(installedBackend);
  const executable = packaged ? installedBackend : devPython;
  const args = packaged ? [] : ['-m', 'bioagent.desktop_service'];
  backend = spawn(executable, args, { cwd: packaged ? path.dirname(installedBackend) : root,
    windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
  backend.on('error', () => win?.webContents.send('bme:event', { event: 'fatal', message: '无法启动本地分析服务，请检查安装包是否完整。' }));
  const lines = readline.createInterface({ input: backend.stdout });
  lines.on('line', line => {
    let value;
    try { value = JSON.parse(line); } catch { return; }
    trace('broker response: ' + (value.id ?? value.event));
    if (value.event) { if (win && !win.isDestroyed()) win.webContents.send('bme:event', value); return; }
    const target = pending.get(value.id);
    if (target) { clearTimeout(target.timer); pending.delete(value.id); target.resolve(value); }
  });
  // Discard diagnostic stderr rather than persisting library errors or credentials.
  backend.stderr.resume();
  backend.on('exit', () => {
    for (const task of pending.values()) {
      clearTimeout(task.timer);
      task.resolve({ ok: false, error: { message: '本地分析服务已退出，请重新启动应用。' } });
    }
    pending.clear();
  });
}

async function choose(operation) {
  const file = operation === 'choose_dataset';
  const selected = await dialog.showOpenDialog(win, {
    title: { choose_library: '选择科研资料文件夹', choose_dataset: '导入 CSV / TSV / XLSX 实验数据',
      choose_monitor: '选择只读图片监控文件夹', choose_output: '选择独立结果目录' }[operation],
    properties: file ? ['openFile'] : ['openDirectory'],
    filters: file ? [{ name: '实验数据', extensions: ['csv', 'tsv','xlsx'] }] : undefined,
  });
  if (selected.canceled || selected.filePaths.length !== 1) return { ok: true, data: { cancelled: true } };
  const chosen = path.resolve(selected.filePaths[0]);
  const action = { choose_library: 'load_library', choose_dataset: 'load_data',
    choose_monitor: 'monitor_start', choose_output: 'set_output' }[operation];
  const result = await request(action, { path: chosen });
  if (operation === 'choose_monitor' && result.ok) monitorPath = chosen;
  return result;
}

app.whenReady().then(async () => {
  trace('app ready');
  const isolated = session.fromPartition('bme-memory-session');
  const assetNames = new Map([['/', 'index.html'], ['/index.html', 'index.html'], ['/styles.css', 'styles.css'], ['/renderer.js', 'renderer.js'], ['/workflow.js', 'workflow.js']]);
  isolated.protocol.handle('bme', async req => {
    const url = new URL(req.url), name = assetNames.get(url.pathname);
    trace('local resource: ' + url.pathname);
    if (url.hostname !== 'app' || !name) return new Response('Not found', { status: 404 });
    const body = await fs.promises.readFile(path.join(__dirname, name));
    const type = name.endsWith('.css') ? 'text/css' : name.endsWith('.js') ? 'text/javascript' : 'text/html';
    return new Response(body, { headers: { 'Content-Type': `${type}; charset=utf-8` } });
  });
  isolated.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  isolated.setPermissionCheckHandler(() => false);
  isolated.webRequest.onBeforeRequest({ urls: ['http://*/*', 'https://*/*', 'file://*/*', 'ws://*/*', 'wss://*/*'] }, (_details, callback) => callback({ cancel: true }));
  win = new BrowserWindow({ width: 1360, height: 900, minWidth: 960, minHeight: 680,
    title: 'BME Agent · 科研工作台', show: false, backgroundColor: '#1a1a1a',
    titleBarStyle: 'hidden', titleBarOverlay: { color: '#181818', symbolColor: '#aaaaaa', height: 39 },
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true,
      sandbox: true, nodeIntegration: false, webSecurity: true, webviewTag: false,
      session: isolated, devTools: false, zoomFactor: 1, defaultFontFamily: { sansSerif: 'Segoe UI' } } });
  win.removeMenu();
  win.webContents.on('did-finish-load', () => trace('renderer loaded'));
  win.webContents.on('did-fail-load', (_event, code) => trace('renderer load failed: ' + code));
  win.webContents.on('render-process-gone', (_event, details) => trace('renderer exited: ' + details.reason));
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (event, url) => { if (!url.startsWith('bme://app/')) event.preventDefault(); });
  win.webContents.on('zoom-changed', event => event.preventDefault());
  ipcMain.handle('bme:attach-files', async (event, paths) => {
    if (event.sender !== win.webContents || event.senderFrame !== win.webContents.mainFrame
      || !event.senderFrame?.url.startsWith('bme://app/') || !Array.isArray(paths) || paths.length < 1 || paths.length > 4
      || paths.some(value => typeof value !== 'string' || value.length > 32700 || !path.isAbsolute(value)))
      return {ok:false,error:{message:'拒绝未授权的附件请求。'}};
    return request('attach_files',{paths});
  });
  ipcMain.handle('bme:invoke', async (event, operation, params) => {
    if (event.sender !== win.webContents || event.senderFrame !== win.webContents.mainFrame
        || !event.senderFrame.url.startsWith('bme://app/') || typeof operation !== 'string'
        || !params || typeof params !== 'object' || JSON.stringify(params).length > 70000) {
      return { ok: false, error: { message: '拒绝未授权的界面请求。' } };
    }
    if (['choose_library', 'choose_dataset', 'choose_monitor', 'choose_output'].includes(operation)) return choose(operation);
    if (operation === 'choose_attachments') {
      const selected = await dialog.showOpenDialog(win,{title:'添加论文、实验数据或图片',properties:['openFile','multiSelections'],
        filters:[{name:'研究附件',extensions:['pdf','txt','md','csv','tsv','xlsx','png','jpg','jpeg','bmp','tif','tiff','webp']}]});
      if (selected.canceled) return {ok:true,data:{cancelled:true}};
      const remaining = Number.isInteger(params.remaining) ? Math.max(1,Math.min(4,params.remaining)) : 4;
      if (selected.filePaths.length > remaining) return {ok:false,error:{message:'当前任务还可添加 '+remaining+' 个附件。'}};
      return request('attach_files',{paths:selected.filePaths.map(value=>path.resolve(value))});
    }
    if (operation === 'resume_monitor') return monitorPath ? request('monitor_start', { path: monitorPath }) : choose('choose_monitor');
    if (operation === 'sandbox_config') return request('sandbox_config', {binary:process.execPath, online:params.online === true});
    if (operation === 'open_keys') { await shell.openExternal('https://platform.openai.com/api-keys'); return { ok: true, data: {} }; }
    if (operation === 'open_billing') { await shell.openExternal('https://platform.openai.com/settings/organization/billing/overview'); return { ok: true, data: {} }; }
    if (operation === 'copy_text' && typeof params.text === 'string') { clipboard.writeText(params.text); return { ok: true, data: {} }; }
    if (operation === 'toggle_sidebar') { win.webContents.send('bme:event', { event: 'toggle_sidebar' }); return { ok: true, data: {} }; }
    if (!publicOperations.has(operation)) return { ok: false, error: { message: '没有提供这项操作。' } };
    return request(operation, params);
  });
  startBackend();
  win.once('ready-to-show', () => win.show());
  await win.loadURL('bme://app/');
  trace('load URL completed');
  for (const [flag, operation] of [['--output','set_output'],['--source','load_library']]) {
    const position = process.argv.indexOf(flag);
    if (position >= 0 && process.argv[position + 1]) await request(operation, {path:path.resolve(process.argv[position+1])});
  }
  if (process.argv.includes('--self-test')) {
    // A real disk-backed File exercises the same capability bridge used by drag-and-drop.
    // Only our synthetic fixture is selected; this path cannot be requested by the renderer.
    await win.webContents.executeJavaScript("const probeInput=document.createElement('input');probeInput.type='file';probeInput.id='offline-file-probe';probeInput.hidden=true;document.body.append(probeInput)");
    win.webContents.debugger.attach('1.3');
    const documentTree = await win.webContents.debugger.sendCommand('DOM.getDocument');
    const probeNode = await win.webContents.debugger.sendCommand('DOM.querySelector',{nodeId:documentTree.root.nodeId,selector:'#offline-file-probe'});
    const fixturePath = fs.existsSync(installedBackend) ? path.join(path.dirname(installedBackend),'_internal','samples','paper_demo.pdf') : path.join(root,'samples','paper_demo.pdf');
    await win.webContents.debugger.sendCommand('DOM.setFileInputFiles',{nodeId:probeNode.nodeId,files:[fixturePath]});
    win.webContents.debugger.detach();
    const test = await win.webContents.executeJavaScript(`(async () => {
      const status = await window.bme.invoke('status');
      const diagnostics = await window.bme.invoke('diagnostics');
      const denied = await window.bme.invoke('load_data', {path:'C:/unapproved.csv'});
      const invalidKey = await window.bme.invoke('connect', {api_key:'bad'});
      const data = await window.bme.invoke('demo_data');
      const chart = await window.bme.invoke('plot', {kind:'折线图',x:'time_s',y:'EMG_mV'});
      const billing = await window.bme.invoke('billing');
      const fakeFile = await window.bme.importFiles([new File(['not a disk file'],'fake.pdf')]);
      const nativeFile = await window.bme.importFiles([...document.getElementById('offline-file-probe').files]);
      if(!nativeFile.ok || nativeFile.data.items.length!==1)throw new Error('Native file bridge failed');
      const imported = nativeFile.data.items[0];
      activeSession().attachments.push(imported);renderAttachments();
      const transfer = new DataTransfer();transfer.items.add(document.getElementById('offline-file-probe').files[0]);
      document.dispatchEvent(new DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true}));
      for(let wait=0;state.busy && wait<100;wait++)await new Promise(resolve=>setTimeout(resolve,30));
      const dropImport = activeSession().attachments.length===2;
      if(!dropImport)throw new Error('Drop import failed');
      await viewAttachment(imported.id,2);
      const attachmentPreview = document.getElementById('source-dialog').open && document.getElementById('source-location').textContent.includes('2 / 2');
      document.getElementById('source-dialog').close();
      await showBilling();
      const billingDialog = document.getElementById('billing-dialog').open;
      document.getElementById('billing-dialog').close();
      // Exercise the real renderer -> IPC -> packaged broker workflow on synthetic data.
      await demoWorkflow('time');
      for(let wait=0;!experiment.profile && wait<150;wait++)await new Promise(resolve=>setTimeout(resolve,30));
      if(!experiment.profile)throw new Error('Experiment profile did not load');
      document.getElementById('wf-exclude-rows').value='1';
      document.getElementById('wf-exclude-reason').value='offline synthetic instrument failure';
      await document.getElementById('wf-preview').onclick();
      const workflowPreview=!!experiment.token && document.getElementById('wf-counts').textContent.includes('116');
      await document.getElementById('wf-render').onclick();
      const workflowTime=!!experiment.run && state.charts[0]?.image.startsWith('data:image/png;base64,');
      const exportProbe=await window.bme.invoke('workflow_export',{run_id:experiment.run});
      const workflowExport=exportProbe.ok && exportProbe.data.path.endsWith('.zip');
      document.getElementById('wf-error').value='SEM';
      document.getElementById('wf-error').dispatchEvent(new Event('input',{bubbles:true}));
      const workflowInvalidation=!experiment.token && !experiment.run && document.getElementById('wf-render').disabled && document.getElementById('wf-export').disabled;
      await demoWorkflow('group');
      for(let wait=0;!experiment.profile && wait<150;wait++)await new Promise(resolve=>setTimeout(resolve,30));
      await document.getElementById('wf-preview').onclick();
      await document.getElementById('wf-render').onclick();
      const workflowGroup=!!experiment.run && document.getElementById('wf-kind').value==='group' && state.charts[0]?.used===15;
      const workflowNoNetwork=(await window.bme.invoke('billing')).data.requests===0;
      if(!workflowPreview || !workflowTime || !workflowExport || !workflowInvalidation || !workflowGroup || !workflowNoNetwork)throw new Error('Experiment workflow regression');
      showPage('chat');
      // Test the actual UI handlers with an offline transport stub. Never use an account key.
      const originalCall = call, uiCalls = [];
      call = async (operation) => {
        uiCalls.push(operation);
        if (operation === 'prepare') return {token:'offline-ui-token', model:'mock-model', preview:'{}', evidence_count:0, instructions:'offline', tools:[]};
        if (operation === 'approve') return {answer:'offline UI check', report_id:'offline-report', citation_issues:[], tokens:{input:1,output:1}, charts:[], warning:''};
        if (operation === 'billing') return billing.data;
        throw new Error('Unexpected offline UI operation');
      };
      state.connected = true; state.dirty = false; state.model = 'mock-model';
      document.getElementById('question').value = 'offline button send';
      await document.getElementById('send').onclick(new MouseEvent('click'));
      const directSend = uiCalls.filter(x => x === 'approve').length === 1 && !document.getElementById('preview-dialog').open;
      const attachedOnSend = activeSession().messages[0].attachments?.length===2;
      document.getElementById('question').value = 'offline optional preview';
      await document.getElementById('preview-request').onclick();
      const optionalPreview = document.getElementById('preview-dialog').open && uiCalls.filter(x => x === 'approve').length === 1;
      document.getElementById('close-preview').click();
      document.getElementById('question').value = 'offline Enter send';
      document.getElementById('question').dispatchEvent(new KeyboardEvent('keydown', {key:'Enter',bubbles:true,cancelable:true}));
      await new Promise(resolve => setTimeout(resolve, 25));
      const enterSend = uiCalls.filter(x => x === 'approve').length === 2 && !document.getElementById('preview-dialog').open;
      call = originalCall;
      if (!directSend || !optionalPreview || !enterSend) throw new Error('Send interaction regression');
      return {title:document.title, dpr:devicePixelRatio, font:getComputedStyle(document.body).fontFamily,
        background:getComputedStyle(document.body).backgroundColor, nodeUnavailable:typeof require==='undefined',
        stateLoaded:status.ok, offlineSDKChecks:diagnostics.data?.local_check, unapprovedPathDenied:!denied.ok, invalidKeyRejected:!invalidKey.ok,
        demoRows:data.data?.rows, pngGenerated:chart.data?.image.startsWith('data:image/png;base64,'),
        billingDialog, balanceUnknown:billing.data?.balance === null && billing.data?.live_balance === false,
        directSend, optionalPreview, enterSend,
        workflowPreview,workflowTime,workflowExport,workflowInvalidation,workflowGroup,workflowNoNetwork,
        nativeFileBridge:!!nativeFile.ok,fakeDiskFileDenied:!fakeFile.ok,attachmentPreview,attachedOnSend,dropImport,
        csp:document.querySelector('meta[http-equiv="Content-Security-Policy"]').content,
        horizontalOverflow:document.documentElement.scrollWidth > innerWidth};
    })()`);
    process.stdout.write(JSON.stringify(test) + '\n');
    app.quit();
  }
  if (process.argv.includes('--smoke-test')) setTimeout(() => app.quit(), 900);
}).catch(() => { process.stderr.write('BME desktop failed to initialize.\n'); app.exit(1); });

app.on('window-all-closed', () => app.quit());
app.on('second-instance', () => { if (win) { if (win.isMinimized()) win.restore(); win.show(); win.focus(); } });
app.on('before-quit', () => { if (backend && !backend.killed) { backend.stdin.end(); backend.kill(); } });
