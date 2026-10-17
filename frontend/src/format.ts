const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
const shortDate = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' })

export const formatMoney = (n: number) => currency.format(n)

// Parse "YYYY-MM-DD" as a local date so it doesn't shift a day in negative UTC offsets.
export function parseIsoDate(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

export const formatDate = (iso: string) => shortDate.format(parseIsoDate(iso))
