import { useState, type FormEvent } from 'react'

interface Props {
  fileName: string
  message: string
  onSubmit: (password: string) => void
  onCancel: () => void
}

export function PasswordPrompt({ fileName, message, onSubmit, onCancel }: Props) {
  const [password, setPassword] = useState('')

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (password) onSubmit(password)
  }

  return (
    <form className="status password" onSubmit={submit}>
      <p>
        <strong>{fileName}</strong>: {message}
      </p>
      <p className="muted small">Banks often use your date of birth or part of your customer ID. Check your bank's email.</p>
      <div className="password-row">
        <input
          className="search"
          type="password"
          autoFocus
          placeholder="PDF password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button type="submit" className="btn primary" disabled={!password}>
          Unlock
        </button>
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}
