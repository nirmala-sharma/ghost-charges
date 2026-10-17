import { formatDate, formatMoney } from '../format'
import type { Subscription } from '../types'

interface Props {
  subscriptions: Subscription[]
}

export function UpcomingCharges({ subscriptions }: Props) {
  const upcoming = subscriptions
    .filter((s) => !s.likely_cancelled)
    .sort((a, b) => a.next_expected.localeCompare(b.next_expected))
    .slice(0, 6)

  if (upcoming.length === 0) return null

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Upcoming charges</h2>
      </div>
      <ul className="upcoming">
        {upcoming.map((s) => (
          <li key={s.merchant}>
            <div>
              <div className="merchant">{s.display_name}</div>
              <div className="muted small">{formatDate(s.next_expected)}</div>
            </div>
            <span className="strong">{formatMoney(s.last_amount)}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
