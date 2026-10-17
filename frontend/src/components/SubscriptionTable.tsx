import { useMemo, useState } from 'react'
import { formatDate, formatMoney } from '../format'
import type { Subscription } from '../types'

type SortKey = 'display_name' | 'cadence' | 'last_amount' | 'monthly_cost' | 'next_expected' | 'confidence'
type Filter = 'all' | 'active' | 'cancelled'

const COLUMNS: { key: SortKey; label: string; numeric?: boolean }[] = [
  { key: 'display_name', label: 'Merchant' },
  { key: 'cadence', label: 'Billing' },
  { key: 'last_amount', label: 'Charge', numeric: true },
  { key: 'monthly_cost', label: 'Per month', numeric: true },
  { key: 'next_expected', label: 'Next charge' },
  { key: 'confidence', label: 'Confidence', numeric: true },
]

interface Props {
  subscriptions: Subscription[]
}

export function SubscriptionTable({ subscriptions }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('monthly_cost')
  const [ascending, setAscending] = useState(false)
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    const filtered = subscriptions.filter((s) => {
      if (filter === 'active' && s.likely_cancelled) return false
      if (filter === 'cancelled' && !s.likely_cancelled) return false
      return !q || s.display_name.toLowerCase().includes(q)
    })
    return [...filtered].sort((a, b) => {
      const av = a[sortKey]
      const bv = b[sortKey]
      const cmp = typeof av === 'number' && typeof bv === 'number' ? av - bv : String(av).localeCompare(String(bv))
      return ascending ? cmp : -cmp
    })
  }, [subscriptions, sortKey, ascending, filter, query])

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) setAscending(!ascending)
    else {
      setSortKey(key)
      setAscending(key === 'display_name' || key === 'next_expected')
    }
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Detected subscriptions</h2>
        <div className="toolbar">
          <input
            className="search"
            type="search"
            placeholder="Search merchant…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="segmented" role="group" aria-label="Filter">
            {(['all', 'active', 'cancelled'] as const).map((f) => (
              <button key={f} type="button" className={filter === f ? 'on' : ''} onClick={() => setFilter(f)}>
                {f[0].toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </div>

      {rows.length === 0 ? (
        <p className="muted empty">No subscriptions match.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {COLUMNS.map((c) => (
                  <th key={c.key} className={c.numeric ? 'num' : ''} aria-sort={sortKey === c.key ? (ascending ? 'ascending' : 'descending') : 'none'}>
                    <button type="button" onClick={() => toggleSort(c.key)}>
                      {c.label}
                      {sortKey === c.key && <span aria-hidden>{ascending ? ' ▲' : ' ▼'}</span>}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.merchant} className={s.likely_cancelled ? 'cancelled' : ''}>
                  <td>
                    <div className="merchant">{s.display_name}</div>
                    <div className="tags">
                      {s.likely_cancelled && <span className="tag neutral">Likely cancelled</span>}
                      {s.price_changed && !s.likely_cancelled && <span className="tag warn">Price changed</span>}
                      <span className="muted small">
                        {s.occurrences} charges since {formatDate(s.first_charge)}
                      </span>
                    </div>
                  </td>
                  <td className="cap">{s.cadence}</td>
                  <td className="num">{formatMoney(s.last_amount)}</td>
                  <td className="num strong">{formatMoney(s.monthly_cost)}</td>
                  <td>{s.likely_cancelled ? <span className="muted">—</span> : formatDate(s.next_expected)}</td>
                  <td className="num">
                    <ConfidenceBar value={s.confidence} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  return (
    <div className="confidence" title={`${pct}% confidence`}>
      <div className="bar">
        <div className="fill" style={{ width: `${pct}%` }} />
      </div>
      <span>{pct}%</span>
    </div>
  )
}
