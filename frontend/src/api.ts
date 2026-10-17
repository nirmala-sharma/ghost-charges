import type { AnalysisResponse } from './types'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function handle(res: Response): Promise<AnalysisResponse> {
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: unknown } | null
    const detail = typeof body?.detail === 'string' ? body.detail : `Request failed (${res.status})`
    throw new ApiError(detail, res.status)
  }
  return res.json() as Promise<AnalysisResponse>
}

export async function analyzeFile(file: File, password?: string): Promise<AnalysisResponse> {
  const form = new FormData()
  form.append('file', file)
  if (password) form.append('password', password)
  return handle(await fetch('/api/analyze', { method: 'POST', body: form }))
}

export async function analyzeSample(): Promise<AnalysisResponse> {
  return handle(await fetch('/api/sample'))
}
