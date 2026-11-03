// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BMEView } from '../src/renderer/src/components/BMEView'
import { Markdown } from '../src/renderer/src/components/Markdown'

const state = vi.hoisted(() => ({ send: vi.fn(), workspace: vi.fn(), session: vi.fn(), requests: [] as string[] }))
vi.mock('../src/renderer/src/lib/agentClient', () => ({
  AgentConnection: class {
    ready = true
    constructor(_c: unknown, open: () => void) { queueMicrotask(open) }
    on() { return () => undefined }
    close() {}
    setWorkspace = state.workspace
    setSession = state.session
    sendMessage = state.send
    stop() {}
  }
}))

const plan = { kind: 'group', x: 'concentration', y: 'signal', group: '', replicate: 'repeat', error: 'SD' }
const conn = { baseUrl: 'http://127.0.0.1:1234', token: 'synthetic-test-token' }

beforeEach(() => {
  state.send.mockReset(); state.workspace.mockReset(); state.session.mockReset(); state.requests.length = 0
  localStorage.clear()
  Element.prototype.scrollIntoView = vi.fn()
  Object.defineProperty(window, 'caelo', { configurable: true, value: {
    coreRequest: vi.fn(async (req: { path: string; body?: string }) => {
      state.requests.push(req.path)
      let data: unknown = {}
      if (req.path === '/bme/status') data = { source_read_only: 'D:/synthetic-source', output: 'D:/synthetic-output', monitor_running: false }
      else if (req.path === '/bme/models') data = { configured: true, models: ['gpt-fixture'], default_model: 'gpt-fixture' }
      else if (req.path === '/agent/sessions') data = { sessions: [{ id: 'old1', title: 'Previous study', cwd: 'D:/unauthorized-old-source' }] }
      else if (req.path === '/agent/sessions/old1') data = { history: [{ role: 'user', content: 'Synthetic question' }] }
      else if (req.path === '/bme/artifacts') data = { files: [] }
      else if (req.path.startsWith('/bme/preview/')) data = { image_uri: 'data:image/png;base64,fixture' }
      else if (req.path === '/bme/tool') {
        const body = JSON.parse(req.body || '{}')
        if (body.name === 'bme_list_sources') data = { files: body.arguments.area === 'samples' ? [{ file: 'samples/biosensor_demo.csv', bytes: 100 }] : [] }
        else if (body.name === 'bme_inspect_table') data = { dataset_id: 'd1', suggested_plan: plan, profile: { rows: 15, columns: ['concentration', 'signal', 'repeat', 'second_signal'].map(name => ({ name, numeric: true, missing: 0 })) }, source_sha256: 'demo-hash', warnings: [] }
        else if (body.name === 'bme_review_chart') data = { review_id: 'r1', used: 15, excluded: 0, warnings: [], summary: [] }
        else throw new Error('Unexpected tool: ' + body.name)
      }
      return { ok: true, status: 200, data }
    }),
    openPath: vi.fn(), selectFolder: vi.fn()
  } })
})
afterEach(cleanup)

describe('BME research boundary in the renderer', () => {
  it('invalidates the saved-review action when a variable changes; local analysis never sends a chat request', async () => {
    render(<BMEView conn={conn} section="data" navigate={vi.fn()} />)
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Source file' }).textContent).toContain('biosensor_demo'))
    fireEvent.click(screen.getByRole('button', { name: 'Inspect table' }))
    await screen.findByRole('button', { name: 'Review & preview' })
    fireEvent.click(screen.getByRole('button', { name: 'Review & preview' }))
    const exportButton = await screen.findByRole('button', { name: 'Confirm and save PNG + analysis ZIP (includes SVG)' })
    await waitFor(() => expect((exportButton as HTMLButtonElement).disabled).toBe(false))
    fireEvent.change(screen.getByRole('combobox', { name: 'Signal Y' }), { target: { value: 'second_signal' } })
    expect(screen.queryByRole('button', { name: 'Confirm and save PNG + analysis ZIP (includes SVG)' })).toBeNull()
    expect(state.send).not.toHaveBeenCalled()
    expect(state.requests.some(p => p.includes('/responses'))).toBe(false)
  })

  it('does not send while Chinese IME is composing; normal Enter sends once with no confirmation dialog', async () => {
    render(<BMEView conn={conn} section="research" navigate={vi.fn()} />)
    await screen.findByRole('option', { name: 'gpt-fixture' })
    const input = screen.getByRole('textbox', { name: 'Research question' })
    fireEvent.change(input, { target: { value: '你好，分析对照实验' } })
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true })
    expect(state.send).not.toHaveBeenCalled()
    fireEvent.keyDown(input, { key: 'Enter', isComposing: false })
    expect(state.send).toHaveBeenCalledExactlyOnceWith('你好，分析对照实验', 'openai', 'gpt-fixture')
    expect(screen.queryByText('Save new analysis outputs')).toBeNull()
  })

  it('restores conversation without granting access to an old source directory', async () => {
    render(<BMEView conn={conn} section="research" navigate={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'History' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Previous study' }))
    await waitFor(() => expect(state.session).toHaveBeenCalledWith('old1'))
    expect(state.workspace).not.toHaveBeenCalledWith('D:/unauthorized-old-source')
  })

  it('renders model-generated HTML as code, not an executable preview', () => {
    const result = render(<Markdown text={'```html\n<script>fetch("https://example.org")</script>\n```'} />)
    expect(result.container.querySelector('iframe')).toBeNull()
    expect(result.container.querySelector('script')).toBeNull()
    expect(result.container.textContent).toContain('fetch')
  })

  it('clears the key input and keeps removal available if account model lookup fails after saving', async () => {
    const previous = window.caelo.coreRequest
    let failModels = false
    vi.spyOn(window.caelo, 'coreRequest').mockImplementation(req => {
      if (failModels && req.path === '/bme/models') return Promise.resolve({ ok: false, status: 502, data: { detail: 'Account models are temporarily unavailable' } })
      return previous(req)
    })
    render(<BMEView conn={conn} section="settings" navigate={vi.fn()} />)
    await waitFor(() => expect((screen.getByRole('button', { name: 'Remove key' }) as HTMLButtonElement).disabled).toBe(false))
    const input = screen.getByLabelText('OpenAI API Key')
    // Password inputs have no textbox role in some jsdom/ARIA versions.
    fireEvent.change(input, { target: { value: 'sk-synthetic-not-a-real-credential' } })
    failModels = true
    fireEvent.click(screen.getByRole('button', { name: 'Save & connect' }))
    await screen.findByText('Account models are temporarily unavailable')
    expect((input as HTMLInputElement).value).toBe('')
    expect((screen.getByRole('button', { name: 'Remove key' }) as HTMLButtonElement).disabled).toBe(false)
    expect(screen.getByRole('alert').textContent).not.toContain('sk-synthetic')
  })
})
