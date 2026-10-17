import { formatMoney } from '../format'
import type { Subscription, Summary } from '../types'

interface Props {
  summary: Summary
  subscriptions: Subscription[]
}

export function SummaryCards({ summary, subscriptions }: Props) {
  const active = subscriptions.filter((s) => !s.likely_cancelled)
  const priceChanges = active.filter((s) => s.price_changed).length

  const cards = [
    { label: 'Monthly spend', value: formatMoney(summary.active_monthly_total), hint: 'active subscriptions' },
    { label: 'Yearly spend', value: formatMoney(summary.active_annual_total), hint: 'at current prices' },
    {
      label: 'Active subscriptions',
      value: String(active.length),
      hint: `${summary.subscriptions_found - active.length} likely cancelled`,
    },
    { label: 'Price changes', value: String(priceChanges), hint: `of ${summary.transactions_analyzed} transactions` },
  ]

  return (
    <div className="cards">
      {cards.map((c) => (
        <div key={c.label} className="card">
          <div className="card-label">{c.label}</div>
          <div className="card-value">{c.value}</div>
          <div className="muted small">{c.hint}</div>
        </div>
      ))}
    </div>
  )
}
