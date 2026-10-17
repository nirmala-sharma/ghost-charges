import { formatMoney } from '../format'
import type { Subscription } from '../types'

interface Props {
  subscriptions: Subscription[]
}

/** Horizontal bars showing each active subscription's share of monthly spend. */
export function SpendBreakdown({ subscriptions }: Props) {
  const active = subscriptions
    .filter((s) => !s.likely_cancelled)
    .sort((a, b) => b.monthly_cost - a.monthly_cost)
  const max = Math.max(...active.map((s) => s.monthly_cost), 1)

  if (active.length === 0) return null

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Where the money goes</h2>
        <span className="muted small">monthly cost</span>
      </div>
      <ul className="breakdown">
        {active.map((s) => (
          <li key={s.merchant}>
            <span className="breakdown-name">{s.display_name}</span>
            <div className="breakdown-track">
              <div className="breakdown-fill" style={{ width: `${(s.monthly_cost / max) * 100}%` }} />
            </div>
            <span className="breakdown-value">{formatMoney(s.monthly_cost)}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
