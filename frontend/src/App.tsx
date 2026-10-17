import { useEffect, useState } from 'react'
import { ApiError, analyzeFile, analyzeSample } from './api'
import { FileUpload } from './components/FileUpload'
import { PasswordPrompt } from './components/PasswordPrompt'
import { SpendBreakdown } from './components/SpendBreakdown'
import { SubscriptionTable } from './components/SubscriptionTable'
import { SummaryCards } from './components/SummaryCards'
import { UpcomingCharges } from './components/UpcomingCharges'
import type { AnalysisResponse } from './types'
import './App.css'

type State =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'password'; file: File; message: string }
  | { status: 'done'; data: AnalysisResponse; source: string }

type Theme = 'light' | 'dark'

function loadTheme(): Theme {
  try {
    return localStorage.getItem('theme') === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

function App() {
  const [state, setState] = useState<State>({ status: 'idle' })
  const [theme, setTheme] = useState<Theme>(loadTheme)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try {
      localStorage.setItem('theme', theme)
    } catch {
      // storage unavailable (private mode) - theme just won't persist
    }
  }, [theme])

  const run = async (request: () => Promise<AnalysisResponse>, source: string, file?: File) => {
    setState({ status: 'loading' })
    try {
      setState({ status: 'done', data: await request(), source })
    } catch (err) {
      if (file && err instanceof ApiError && err.status === 401) {
        setState({ status: 'password', file, message: err.message })
      } else {
        setState({ status: 'error', message: err instanceof Error ? err.message : 'Something went wrong' })
      }
    }
  }

  const runFile = (file: File, password?: string) => run(() => analyzeFile(file, password), file.name, file)

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>Subscription Detector</h1>
          <p className="muted">Upload a bank statement to find recurring charges and see what they cost you.</p>
        </div>
        <button
          type="button"
          className="btn"
          onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}
          aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
        >
          {theme === 'light' ? '🌙 Dark' : '☀️ Light'}
        </button>
      </header>

      <FileUpload
        disabled={state.status === 'loading'}
        onFile={(file) => runFile(file)}
        onSample={() => run(analyzeSample, 'sample data')}
      />

      {state.status === 'password' && (
        <PasswordPrompt
          key={state.message}
          fileName={state.file.name}
          message={state.message}
          onSubmit={(password) => runFile(state.file, password)}
          onCancel={() => setState({ status: 'idle' })}
        />
      )}

      {state.status === 'loading' && <p className="status">Analyzing transactions…</p>}
      {state.status === 'error' && (
        <p className="status error" role="alert">
          {state.message}
        </p>
      )}

      {state.status === 'done' && (
        <main className="results">
          <p className="muted small">
            Results for <strong>{state.source}</strong>
          </p>
          {state.data.subscriptions.length === 0 ? (
            <p className="status">No recurring charges found in {state.data.summary.transactions_analyzed} transactions.</p>
          ) : (
            <>
              <SummaryCards summary={state.data.summary} subscriptions={state.data.subscriptions} />
              <div className="grid">
                <SpendBreakdown subscriptions={state.data.subscriptions} />
                <UpcomingCharges subscriptions={state.data.subscriptions} />
              </div>
              <SubscriptionTable subscriptions={state.data.subscriptions} />
            </>
          )}
        </main>
      )}
    </div>
  )
}

export default App
