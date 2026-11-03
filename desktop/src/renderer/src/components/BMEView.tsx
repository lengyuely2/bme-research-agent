import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUp, Check, ChevronDown, FileText, FolderOpen, History, LoaderCircle, RefreshCw, ShieldCheck, Square, X } from 'lucide-react'
import { AgentConnection, type AgentEvent } from '../lib/agentClient'
import type { Conn } from '../lib/api'
import { Markdown } from './Markdown'
import { Button } from './ui/Button'
import { BrandMark } from './ui/BrandMark'
import { BMEBalance, type Balance } from './BMEBalance'

export type Section = 'research' | 'data' | 'papers' | 'monitor' | 'settings'
type Value = Record<string, unknown>
type FileInfo = { file: string; bytes: number }
type Status = { source_read_only: string; output: string; monitor_running: boolean; balance?: Balance; openai_configured?: boolean }
type Message = { role: 'user' | 'assistant' | 'tool' | 'error'; text: string; id?: string }
type Session = { id: string; title: string; cwd: string }
type Plan = Record<string, string>
type Inspection = { dataset_id: string; suggested_plan: Plan; profile: { rows: number; columns: { name: string; missing: number; numeric: boolean }[] }; source_sha256: string; warnings: string[] }
type Review = { review_id: string; used: number; excluded: number; warnings: string[]; summary: Value[] }

async function request<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const r = await window.caelo.coreRequest({ path, method: method || (body === undefined ? 'GET' : 'POST'), body: body === undefined ? undefined : JSON.stringify(body), timeoutMs: 90000 })
  if (!r.ok) {
    const data = r.data as { detail?: string; error?: string } | undefined
    throw new Error(data?.detail || data?.error || r.error || `Request failed (${r.status})`)
  }
  return r.data as T
}
const localTool = <T,>(name: string, args: Value = {}) => request<T>('/bme/tool', { name: 'bme_' + name, arguments: args })
const basename = (p: string) => p.replace(/\\/g, '/').split('/').pop() || p
const prompts = ['Review biosensor controls and sources of error', 'Summarize a paper: methods, evidence, limitations', 'Inspect data and propose a verifiable chart plan']

export function BMEView({ conn, section, navigate }: { conn: Conn; section: Section; navigate: (s: Section) => void }) {
  const { baseUrl, token } = conn
  const [status, setStatus] = useState<Status | null>(null)
  const [models, setModels] = useState<string[]>([])
  const [model, setModel] = useState(() => localStorage.getItem('bme.model') || '')
  const [configured, setConfigured] = useState(false)
  const [connected, setConnected] = useState(false)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [approval, setApproval] = useState<Extract<AgentEvent, { type: 'approval_request' }> | null>(null)
  const [usage, setUsage] = useState('')
  const [sessions, setSessions] = useState<Session[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [files, setFiles] = useState<FileInfo[]>([])
  const [file, setFile] = useState('samples/biosensor_demo.csv')
  const [inspection, setInspection] = useState<Inspection | null>(null)
  const [plan, setPlan] = useState<Plan>({})
  const [review, setReview] = useState<Review | null>(null)
  const [preview, setPreview] = useState('')
  const [artifacts, setArtifacts] = useState<{ name: string; bytes: number }[]>([])
  const [paper, setPaper] = useState<Value | null>(null)
  const [page, setPage] = useState(1)
  const [image, setImage] = useState('')
  const [folder, setFolder] = useState('')
  const [events, setEvents] = useState<Value[]>([])
  const [key, setKey] = useState('')
  const agent = useRef<AgentConnection | null>(null)
  const activeSession = useRef<string | null>(null)
  const busyRef = useRef(false)
  const bottom = useRef<HTMLDivElement>(null)
  const readySource = useRef('')
  busyRef.current = busy

  const refresh = useCallback(async () => {
    const [s, source, samples, outputs, saved] = await Promise.all([
      request<Status>('/bme/status'), localTool<{ files: FileInfo[] }>('list_sources'),
      localTool<{ files: FileInfo[] }>('list_sources', { area: 'samples' }),
      request<{ files: { name: string; bytes: number }[] }>('/bme/artifacts'), request<{ sessions: Session[] }>('/agent/sessions')
    ])
    setStatus(s); setFiles([...source.files, ...samples.files]); setArtifacts(outputs.files); setSessions(saved.sessions)
    if (typeof s.openai_configured === 'boolean') setConfigured(s.openai_configured)
    return s
  }, [])
  const refreshModels = useCallback(async () => {
    const r = await request<{ models: string[]; configured: boolean; default_model?: string }>('/bme/models')
    setModels(r.models); setConfigured(r.configured)
    setModel(previous => r.models.includes(previous) ? previous : r.default_model || '')
  }, [])
  async function perform(task: () => Promise<void>) {
    setWorking(true); setError('')
    try { await task() } catch (e) { setError(String((e as Error).message)) } finally { setWorking(false) }
  }

  useEffect(() => {
    let disposed = false
    const a = new AgentConnection({ baseUrl, token }, () => {
      if (disposed) return
      setConnected(true)
      // Reconnect restores context only; it never replays a paid request.
      if (readySource.current) a.setWorkspace(readySource.current)
      if (activeSession.current) a.setSession(activeSession.current)
    }, () => { setConnected(false); setBusy(false); setApproval(null) })
    agent.current = a
    const off = a.on(e => {
      if (disposed) return
      if (e.type === 'session') activeSession.current = e.id
      if (e.type === 'workspace') { readySource.current = e.path; void refresh().catch(err => setError(err.message)) }
      if (e.type === 'assistant_done') setMessages(prev => prev.at(-1)?.role === 'assistant' ? [...prev.slice(0, -1), { role: 'assistant', text: e.content }] : [...prev, { role: 'assistant', text: e.content }])
      if (e.type === 'text') setMessages(prev => prev.at(-1)?.role === 'assistant' ? [...prev.slice(0, -1), { role: 'assistant', text: e.full }] : [...prev, { role: 'assistant', text: e.full }])
      if (e.type === 'tool_call') setMessages(prev => [...prev, { role: 'tool', id: e.id, text: e.name.replace('bme_', '') + ' · running' }])
      if (e.type === 'tool_result') setMessages(prev => prev.map(m => m.id === e.id ? { ...m, text: e.summary, role: e.ok ? 'tool' : 'error' } : m))
      if (e.type === 'approval_request') setApproval(e)
      if (e.type === 'error') { setError(e.error); setBusy(false); setApproval(null) }
      if (e.type === 'done') { setBusy(false); setApproval(null); void refresh().catch(err => setError(err.message)) }
      if (e.type === 'usage') setUsage(`${e.input_tokens.toLocaleString()} input · ${e.output_tokens.toLocaleString()} output tokens`)
    })
    void refresh().then(s => { if (!disposed) { readySource.current = s.source_read_only; if (a.ready) a.setWorkspace(s.source_read_only) } }).catch(e => setError(e.message))
    void refreshModels().catch(e => setError(e.message))
    const newSession = () => { if (busyRef.current) return; a.setSession(null); activeSession.current = null; setMessages([]); setError(''); setUsage('') }
    window.addEventListener('bme-new-session', newSession)
    return () => { disposed = true; off(); a.close(); window.removeEventListener('bme-new-session', newSession) }
  }, [baseUrl, token, refresh, refreshModels])
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [messages, approval])
  useEffect(() => { if (model) localStorage.setItem('bme.model', model) }, [model])
  useEffect(() => {
    if (section !== 'monitor' || !status?.monitor_running) return
    let disposed = false, pending = false
    const timer = setInterval(() => {
      if (pending) return
      pending = true
      void localTool<{ events: Value[] }>('image_monitor_events').then(r => {
        if (!disposed && r.events.length) setEvents(p => [...r.events, ...p].slice(0, 200))
      }).catch(e => { if (!disposed) setError(e.message) }).finally(() => { pending = false })
    }, 2000)
    return () => { disposed = true; clearInterval(timer) }
  }, [section, status?.monitor_running, status?.source_read_only])

  function changeFile(next: string) { setFile(next); setInspection(null); setReview(null); setPreview(''); setPaper(null); setImage(''); setPage(1) }
  function changePlan(field: string, value: string) { setPlan(p => ({ ...p, [field]: value })); setReview(null); setPreview('') }
  function send(text = input) {
    if (!text.trim() || busy || !connected || !model || working) return
    setMessages(prev => [...prev, { role: 'user', text }]); setInput(''); setError(''); setBusy(true)
    agent.current?.sendMessage(text, 'openai', model)
  }
  async function chooseSource() {
    const path = await window.caelo.selectFolder()
    if (!path || busy) return
    setInspection(null); setReview(null); setPreview(''); setPaper(null); setEvents([])
    agent.current?.setWorkspace(path)
  }
  async function resume(s: Session) {
    const data = await request<{ history: { role: string; content: unknown }[] }>(`/agent/sessions/${encodeURIComponent(s.id)}`)
    // Restoring history grants no access to the session's previous source folder.
    agent.current?.setSession(s.id)
    setMessages(data.history.filter(m => ['user', 'assistant'].includes(m.role) && typeof m.content === 'string').map(m => ({ role: m.role as 'user' | 'assistant', text: m.content as string })))
    activeSession.current = s.id; setHistoryOpen(false)
  }
  const disabled = busy || working
  const fileSelect = <select aria-label="Source file" value={file} onChange={e => changeFile(e.target.value)} className="bme-field min-w-0 flex-1" disabled={disabled}>{files.map(f => <option key={f.file} value={f.file}>{f.file}</option>)}</select>
  const headings = { research: 'Research chat', data: 'Data analysis & plots', papers: 'Papers & evidence', monitor: 'Image watch', settings: 'Connection & settings' }

  return <main className="flex min-w-0 flex-1 flex-col">
    <header className="bme-header flex h-[68px] shrink-0 items-center justify-between border-b border-border px-7"><div className="flex items-center gap-2 text-sm"><span className="text-muted">BME</span><span className="mx-2 text-muted/40">/</span>{headings[section]}</div><div className="flex items-center gap-3"><button disabled={disabled} onClick={() => void perform(chooseSource)} title={status?.source_read_only} className="bme-source"><FolderOpen size={15} />{status?.source_read_only && basename(status.source_read_only) !== 'empty-source' ? basename(status.source_read_only) : 'Connect source folder'}<ChevronDown size={13} /></button><span className="bme-balance" title="Manually recorded balance snapshot; not a live account balance">{status?.balance?.amount == null ? 'Balance —' : `Balance ${status.balance.currency} ${status.balance.amount.toFixed(2)} · manual`}</span><span className="bme-status"><i className={connected ? 'ready' : ''} />{connected ? 'Local service ready' : 'Connecting'}</span></div></header>
    {error && <div role="alert" className="bme-error mx-7 mt-4 flex items-start justify-between gap-4"><span>{error}</span><button aria-label="Dismiss message" onClick={() => setError('')}><X size={16} /></button></div>}
    <section className="bme-research min-h-0 flex-1 flex-col" style={{ display: section === 'research' ? 'flex' : 'none' }}>
      <div className="flex shrink-0 justify-end gap-2 px-7 pt-4"><button className="bme-link flex items-center gap-2" onClick={() => setHistoryOpen(!historyOpen)}><History size={14} />History</button></div>
      {historyOpen && <div className="bme-history mx-auto w-full max-w-3xl p-4"><div className="mb-3 flex justify-between text-sm"><span>Locally saved research sessions</span><button onClick={() => setHistoryOpen(false)}><X size={16} /></button></div>{sessions.length ? sessions.map(s => <button disabled={disabled} key={s.id} onClick={() => void perform(() => resume(s))} className="block w-full truncate rounded-lg p-2 text-left text-sm hover:bg-surface-2">{s.title || 'Research task'}</button>) : <p className="text-sm text-muted">Conversations are saved locally after the first completed turn.</p>}</div>}
      <div className="min-h-0 flex-1 overflow-y-auto px-8"><div className="mx-auto max-w-[820px] py-6">
        {!messages.length && <div className="bme-welcome"><BrandMark size={54} className="mx-auto mb-6" /><div className="bme-eyebrow">YOUR RESEARCH, ONE STEP FORWARD</div><h1>What will you discover today?</h1><p>From data to evidence. A clearer path for your research.</p><div className="bme-suggestions">{prompts.map((p, i) => <button key={p} onClick={() => setInput(p)}><span>0{i + 1}</span>{p}</button>)}</div><div className="mt-6 flex justify-center gap-5 text-[11px] text-muted"><span>Biosensing</span><span>Disease detection</span><span>Reproducible analysis</span></div></div>}
        {messages.map((m, i) => <div key={i} className={`bme-message ${m.role}`}>{m.role === 'tool' ? <details><summary><Check size={13} />Local analysis tool</summary><pre>{m.text}</pre></details> : m.role === 'user' ? <div className="bme-user-bubble">{m.text}</div> : <Markdown text={m.text} />}</div>)}
        {busy && <div className="my-5 flex items-center gap-2 text-xs text-muted"><LoaderCircle size={14} className="animate-spin" />Researching…</div>}
        {approval && <div className="bme-card mt-4"><h3>Save new analysis outputs</h3><p className="my-3 text-sm text-muted">{approval.detail?.description || 'Save a new output file. Original sources remain read-only.'}</p><pre className="bme-json">{JSON.stringify(approval.detail?.args || {}, null, 2)}</pre><div className="mt-4 flex gap-3"><Button size="sm" onClick={() => { agent.current?.approve(approval.id, 'accept'); setApproval(null) }}>Confirm save</Button><Button variant="ghost" size="sm" onClick={() => { agent.current?.approve(approval.id, 'reject'); setApproval(null) }}>Cancel</Button></div></div>}
        <div ref={bottom} />
      </div></div>
      <div className="mx-auto w-full max-w-[884px] px-8 pt-3 pb-6"><div className="bme-composer"><textarea aria-label="Research question" placeholder="Ask a research question, or analyze your connected experiment files…" value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send() } }} /><div className="flex items-center justify-between gap-3 px-4 pb-3"><div className="flex min-w-0 items-center gap-3"><select aria-label="GPT model" className="bme-model" value={model} onChange={e => setModel(e.target.value)} disabled={disabled}><option value="">{configured ? 'Refresh and select a model' : 'Connect GPT'}</option>{models.map(m => <option key={m}>{m}</option>)}</select><button className="text-muted" title="Refresh account models" disabled={disabled} onClick={() => void perform(refreshModels)}><RefreshCw size={13} /></button><span className="hidden text-[11px] text-muted xl:inline">Bounded BME tools</span></div>{busy ? <button className="bme-send" title="Stop" onClick={() => agent.current?.stop()}><Square size={15} /></button> : <button className="bme-send" title="Send" disabled={!input.trim() || !model || !connected || disabled} onClick={() => send()}><ArrowUp size={18} /></button>}</div></div><div className="mt-3 flex justify-between text-[10px] text-muted"><span>Read-only sources · Tool-read text/images are sent to OpenAI</span><span>{usage || 'Enter to send · Shift + Enter for a new line'}</span></div>{!configured && <button className="bme-link mt-3 text-xs" onClick={() => navigate('settings')}>Connect your OpenAI API first →</button>}</div>
    </section>
    {section !== 'research' && <section className="min-h-0 flex-1 overflow-y-auto p-8"><div className="mx-auto max-w-[1040px]">
      {section === 'data' && <><div className="bme-page-title"><p>LOCAL ANALYSIS</p><h1>Every figure starts with evidence.</h1><span>Inspect → verify variables and replicates → preview → export. All calculations run locally.</span></div><div className="bme-card"><h3>01 · Select data</h3><div className="mt-4 flex gap-3">{fileSelect}<Button disabled={disabled || !file} onClick={() => void perform(async () => { setReview(null); setPreview(''); setPaper(null); const r = await localTool<Inspection>('inspect_table', { file }); setInspection(r); setPlan(r.suggested_plan) })}>Inspect table</Button></div><p className="mt-3 text-xs text-muted">CSV / TSV / XLSX and Spark kinetics tables. Files under samples/ are synthetic fixtures.</p></div>
      {inspection && <div className="bme-card mt-5"><div className="flex justify-between"><h3>02 · Verify the chart plan</h3><span className="text-xs text-muted">{inspection.profile.rows} records · {inspection.profile.columns.length} columns</span></div><div className="mt-5 grid grid-cols-2 gap-4 lg:grid-cols-3">{['x', 'y', 'group', 'replicate'].map(k => <label key={k} className="bme-label">{({ x: 'X axis', y: 'Signal Y', group: 'Group (optional)', replicate: 'Replicate ID' } as Plan)[k]}<select className="bme-field" value={plan[k] || ''} disabled={disabled} onChange={e => changePlan(k, e.target.value)}><option value="">Not specified</option>{inspection.profile.columns.map(c => <option key={c.name}>{c.name}</option>)}</select></label>)}<label className="bme-label">Chart type<select className="bme-field" value={plan.kind || 'group'} onChange={e => changePlan('kind', e.target.value)} disabled={disabled}><option value="group">Concentration / grouped response</option><option value="time">Kinetics / time course</option></select></label><label className="bme-label">Error bars<select className="bme-field" value={plan.error || 'SD'} onChange={e => changePlan('error', e.target.value)} disabled={disabled}><option>SD</option><option>SEM</option></select></label></div><details className="mt-5 text-sm text-muted"><summary>Ranges and manual exclusions</summary><div className="mt-3 grid grid-cols-2 gap-4">{[['x_min', 'X minimum'], ['x_max', 'X maximum'], ['exclude_rows', 'Record numbers to exclude (e.g. 3,7)'], ['exclude_reason', 'Independent experimental / statistical reason']].map(([k, label]) => <label key={k} className="bme-label">{label}<input className="bme-field" value={plan[k] || ''} disabled={disabled} onChange={e => changePlan(k, e.target.value)} /></label>)}</div><p className="mt-3 text-xs">Spike flags are candidates. Never remove data to force a rising trend. Exclusions require an independent reason.</p></details><div className="mt-5 flex gap-3"><Button disabled={disabled} onClick={() => void perform(async () => { const r = await localTool<Review>('review_chart', { dataset_id: inspection.dataset_id, plan }); setReview(r); setPreview(''); const p = await request<{ image_uri: string }>(`/bme/preview/${r.review_id}`); setPreview(p.image_uri) })}>Review & preview</Button><Button variant="outline" disabled={disabled} onClick={() => void perform(async () => { setPaper(await localTool<Value>('spike_candidates', { dataset_id: inspection.dataset_id })) })}>Flag spike candidates</Button></div><p className="mt-3 break-all text-[10px] text-muted">Source SHA-256 · {inspection.source_sha256}</p></div>}
      {review && <div className="bme-card mt-5"><h3>03 · Preview and export</h3><p className="my-3 text-sm text-muted">Included {review.used} records · Excluded {review.excluded} records. {review.warnings?.join(' ')}</p>{preview && <img src={preview} alt="Local chart preview" className="w-full rounded-xl bg-white" />}<details className="mt-4"><summary className="text-sm text-muted">View aggregate statistics</summary><pre className="bme-json">{JSON.stringify(review.summary, null, 2)}</pre></details><Button className="mt-5" disabled={disabled || !preview} onClick={() => void perform(async () => { await localTool('export_chart', { review_id: review.review_id }); await refresh() })}>Confirm and save PNG + analysis ZIP (includes SVG)</Button></div>}
      {paper && <details className="bme-card mt-5"><summary>Spike candidates (no automatic exclusions)</summary><pre className="bme-json">{JSON.stringify(paper, null, 2)}</pre></details>}
      <div className="bme-card mt-5"><div className="flex justify-between"><h3>Generated outputs</h3><button className="bme-link text-xs" onClick={() => status && void window.caelo.openPath(status.output)}>Open output folder ↗</button></div>{artifacts.length ? artifacts.slice(0, 12).map(a => <button key={a.name} className="bme-output" onClick={() => void perform(async () => { if (!a.name.endsWith('.png')) { if (status) await window.caelo.openPath(status.output); return } const r = await request<{ data_uri: string }>(`/bme/artifacts/${encodeURIComponent(a.name)}`); setImage(r.data_uri) })}><FileText size={15} /><span>{a.name}</span><small>{(a.bytes / 1024).toFixed(1)} KB</small></button>) : <p className="mt-4 text-sm text-muted">No outputs yet. Try the full workflow with a synthetic sample.</p>}{image && <img src={image} alt="Exported analysis figure" className="mt-4 w-full rounded-xl" />}</div></>}
      {section === 'papers' && <><div className="bme-page-title"><p>EVIDENCE FIRST</p><h1>From papers to your next experiment.</h1><span>Local reading makes no API call. Send the file to GPT only when you choose to analyze it.</span></div><div className="bme-card"><h3>Read evidence</h3><div className="mt-4 flex gap-3">{fileSelect}<input aria-label="PDF page" className="bme-field w-20" type="number" min={1} value={page} onChange={e => setPage(Math.max(1, Number(e.target.value)))} /><Button disabled={disabled} onClick={() => void perform(async () => { setImage(''); setPaper(await localTool<Value>('read_document', { file, page })) })}>Read locally</Button></div><div className="mt-4 flex gap-3"><Button variant="outline" disabled={disabled} onClick={() => void perform(async () => { const r = await localTool<{ image_uri: string }>('paper_page', { file, page }); setImage(r.image_uri) })}>Preview PDF page</Button><Button variant="outline" disabled={disabled} onClick={() => { setInput(`Read ${file}. Summarize the research question, methods, controls, evidence, and limitations. Cite physical PDF page numbers. Do not invent unreported conditions.`); navigate('research') }}>Analyze with GPT</Button></div>{paper && <div className="mt-5"><p className="text-xs text-muted">{String(paper.citation || '')}</p><pre className="bme-paper">{String(paper.text || JSON.stringify(paper, null, 2))}</pre></div>}{image && <img src={image} alt="Physical PDF page preview" className="mt-5 max-w-full rounded-xl" />}</div></>}
      {section === 'monitor' && <><div className="bme-page-title"><p>LOCAL IMAGE WATCH</p><h1>Keep an eye on new experiment images.</h1><span>Watch for new images in your source folder. Record names, sizes, and timestamps without automatic uploads or model calls.</span></div><div className="bme-card"><h3>Watch folder</h3><p className="mt-3 break-all text-xs text-muted">{status?.source_read_only}</p><div className="mt-4 flex gap-3"><input aria-label="Watch subfolder" className="bme-field flex-1" placeholder="Relative subfolder; leave empty to watch the source folder" value={folder} onChange={e => setFolder(e.target.value)} disabled={disabled || status?.monitor_running} /><Button disabled={disabled || status?.monitor_running} onClick={() => void perform(async () => { await localTool('start_image_monitor', { folder }); await refresh() })}>Start watching</Button><Button variant="outline" disabled={disabled || !status?.monitor_running} onClick={() => void perform(async () => { await request('/bme/monitor/stop', {}); await refresh() })}>Stop</Button></div><div className="mt-5 flex items-center justify-between"><span className="text-sm text-muted">{status?.monitor_running ? 'Watching · checking stable files every 2 seconds' : 'Watch is stopped'}</span><Button variant="ghost" disabled={disabled} onClick={() => void perform(async () => { const r = await localTool<{ events: Value[] }>('image_monitor_events'); setEvents(p => [...r.events, ...p].slice(0, 200)) })}>Refresh image events</Button></div>{events.length ? events.map((e, i) => <div className="bme-output" key={i}><FileText size={15} /><span>{String(e.name)}</span><small>{String(e.bytes)} bytes</small></div>) : <div className="bme-empty">New images appear automatically after their writes stabilize.</div>}</div></>}
      {section === 'settings' && <><div className="bme-page-title"><p>YOUR MODEL, YOUR WORKSPACE</p><h1>Connect your research assistant.</h1><span>Connect through the OpenAI API. This build does not import credentials from other apps.</span></div><div className="bme-card"><h3>OpenAI GPT</h3><p className="my-3 text-sm text-muted">{configured ? 'API key configured. It is stored using Windows-backed encryption.' : 'Enter an API key to load models available to your account.'}</p><div className="flex gap-3"><input aria-label="OpenAI API Key" type="password" autoComplete="off" spellCheck={false} placeholder="sk-…" className="bme-field flex-1" value={key} onChange={e => setKey(e.target.value)} /><Button disabled={disabled || !key.trim()} onClick={() => void perform(async () => { await request('/settings', { openai_api_key: key.trim() }, 'PUT'); setKey(''); setConfigured(true); await refreshModels() })}>Save & connect</Button></div><div className="mt-4 flex gap-3"><Button variant="outline" disabled={disabled} onClick={() => void perform(refreshModels)}>Refresh account models</Button><Button variant="ghost" disabled={disabled || !configured} onClick={() => void perform(async () => { await request('/settings/openai-api-key', undefined, 'DELETE'); setConfigured(false); setModels([]); setModel('') })}>Remove key</Button></div><p className="mt-4 text-xs text-muted">Models come from your account /models endpoint. Availability does not guarantee tool or image support. Errors are shown without silently changing models.</p><a className="bme-link mt-4 inline-block text-sm" href="https://platform.openai.com/settings/organization/billing/overview" target="_blank" rel="noreferrer">Open official usage & billing ↗</a><p className="mt-2 text-xs text-muted">Record a manual snapshot below. Token estimates are never presented as your account balance.</p></div><BMEBalance value={status?.balance} onSaved={balance => setStatus(s => s ? { ...s, balance } : s)} /><div className="bme-card mt-5"><h3 className="flex items-center gap-2"><ShieldCheck size={17} />Files and privacy</h3><p className="my-3 text-sm leading-7 text-muted">Source files are read-only and outputs are saved separately. Chat sends directly; saving a model-generated chart or draft requires one approval. Tool-read text and images enter the OpenAI context and local history. Image monitoring records metadata only.</p><p className="text-xs leading-6 text-muted">Arbitrary commands, external app control, source overwrite/deletion, third-party MCP, hooks, and automatic updates are disabled. These are application-level controls, not an operating-system sandbox.</p><p className="mt-4 break-all text-xs text-muted">Output folder · {status?.output}</p><p className="mt-4 text-xs text-muted">An independent BME integration based on AuraVixStudio/Caelo (Apache-2.0).</p></div></>}
      {working && <div className="mt-5 flex items-center gap-2 text-xs text-muted"><LoaderCircle size={14} className="animate-spin" />Processing…</div>}
    </div></section>}
  </main>
}
