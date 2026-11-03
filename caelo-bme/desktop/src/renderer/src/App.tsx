import { useState } from 'react'
import { Activity, BookOpen, ChartNoAxesCombined, MessageSquare, PanelLeftClose, PanelLeftOpen, Settings, ShieldCheck } from 'lucide-react'
import { useConnection } from './lib/useConnection'
import { BrandMark } from './components/ui/BrandMark'
import { BMEView, type Section } from './components/BMEView'
import { cn } from './lib/cn'
import './bme.css'

const modules = [
  { id: 'research', label: 'Research chat', icon: MessageSquare },
  { id: 'data', label: 'Data analysis & plots', icon: ChartNoAxesCombined },
  { id: 'papers', label: 'Papers & evidence', icon: BookOpen },
  { id: 'monitor', label: 'Image watch', icon: Activity },
  { id: 'settings', label: 'Connection & settings', icon: Settings }
] as const

export default function App() {
  const connection = useConnection()
  const [section, setSection] = useState<Section>('research')
  const [collapsed, setCollapsed] = useState(false)
  const conn = connection.status === 'ready' && connection.baseUrl && connection.token
    ? { baseUrl: connection.baseUrl, token: connection.token } : null
  return <div className="bme-app flex h-screen overflow-hidden bg-bg text-fg">
    <aside className={cn('bme-rail flex shrink-0 flex-col border-r border-border', collapsed ? 'w-[74px]' : 'w-[244px]')}>
      <div className="flex h-[88px] items-center gap-3 px-5"><BrandMark size={32} />{!collapsed && <div><strong className="text-base tracking-tight">Caelo <span className="font-normal text-muted">BME</span></strong><p className="mt-1 text-[11px] text-muted">Biosensing · Disease detection</p></div>}</div>
      <div className="px-3"><button className="bme-new" title="New research task" onClick={() => { setSection('research'); window.dispatchEvent(new Event('bme-new-session')) }}>＋ {!collapsed && 'New research task'}</button></div>
      <p className="mt-8 mb-3 px-6 text-[10px] tracking-[.16em] text-muted">{collapsed ? 'BME' : 'RESEARCH WORKSPACE'}</p>
      <nav className="flex flex-col gap-1 px-3">{modules.map(m => <button key={m.id} title={m.label} onClick={() => setSection(m.id)} className={cn('bme-nav', section === m.id && 'active')}><m.icon size={17} />{!collapsed && m.label}</button>)}</nav>
      <div className="mt-auto border-t border-border p-5"><div className="flex items-center gap-2 text-xs text-muted"><ShieldCheck size={15} className="text-emerald-400" />{!collapsed && 'Sources are read-only'}</div>{!collapsed && <p className="mt-2 text-[10px] leading-relaxed text-muted">Caelo UI · Local BME tools<br />GPT reasoning · Separate outputs</p>}<button title="Toggle sidebar" className="mt-5 text-muted" onClick={() => setCollapsed(!collapsed)}>{collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}</button></div>
    </aside>
    {conn ? <BMEView conn={conn} section={section} navigate={setSection} /> : <main className="flex flex-1 items-center justify-center"><div className="text-center"><BrandMark size={48} className="mx-auto mb-5" /><p>{connection.status === 'starting' ? 'Starting your research workspace…' : 'Backend is not ready'}</p><p className="mt-3 max-w-lg text-sm text-muted">{connection.error || 'The first launch may take a few seconds.'}</p></div></main>}
  </div>
}
