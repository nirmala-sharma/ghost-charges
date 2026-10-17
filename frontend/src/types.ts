// Mirrors the Pydantic response models in backend/app/main.py.

export type Cadence = 'weekly' | 'biweekly' | 'monthly' | 'quarterly' | 'yearly'

export interface Subscription {
  merchant: string
  display_name: string
  cadence: Cadence
  average_amount: number
  last_amount: number
  monthly_cost: number
  annual_cost: number
  occurrences: number
  first_charge: string // ISO date
  last_charge: string
  next_expected: string
  confidence: number // 0..1
  price_changed: boolean
  likely_cancelled: boolean
}

export interface Summary {
  transactions_analyzed: number
  subscriptions_found: number
  active_monthly_total: number
  active_annual_total: number
}

export interface AnalysisResponse {
  summary: Summary
  subscriptions: Subscription[]
}
