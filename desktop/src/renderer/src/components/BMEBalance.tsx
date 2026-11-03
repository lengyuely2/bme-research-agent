import { useEffect, useState } from 'react'
import { Button } from './ui/Button'

export type Balance = { amount: number | null; currency: 'USD' | 'CNY'; recorded_at: string; source: 'manual' }

export function BMEBalance({ value, onSaved }: { value?: Balance; onSaved: (b: Balance) => void }) {
  const [amount, setAmount] = useState('')
  const [currency, setCurrency] = useState<'USD' | 'CNY'>('USD')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { setAmount(value?.amount == null ? '' : String(value.amount)); setCurrency(value?.currency || 'USD') }, [value?.amount, value?.currency])
  async function save() {
    setBusy(true); setError('')
    try {
      const result = await window.caelo.coreRequest({ path: '/bme/balance', method: 'PUT', body: JSON.stringify({ amount: amount.trim() ? Number(amount) : null, currency }) })
      if (!result.ok) throw new Error('Balance not saved. Enter a number between 0 and 1,000,000.')
      onSaved(result.data as Balance)
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <div className="bme-card mt-5"><h3>API balance · Manual snapshot</h3><p className="my-3 text-xs leading-6 text-muted">Copy the balance from official Billing. This stores a manual amount and timestamp, with no account query or automatic deductions. Save an empty value to clear the snapshot.</p><div className="flex gap-3"><input aria-label="Manual balance" type="number" min="0" max="1000000" step="0.01" className="bme-field flex-1" value={amount} onChange={e => setAmount(e.target.value)} placeholder="Not recorded" /><select aria-label="Balance currency" className="bme-field" value={currency} onChange={e => setCurrency(e.target.value as 'USD' | 'CNY')}><option>USD</option><option>CNY</option></select><Button disabled={busy} onClick={() => void save()}>Save balance snapshot</Button></div>{value?.recorded_at && <p className="mt-3 text-xs text-muted">Recorded at · {new Date(value.recorded_at).toLocaleString('en-US')}</p>}{error && <p role="alert" className="mt-3 text-xs text-red-300">{error}</p>}</div>
}
