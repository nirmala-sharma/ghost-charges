import { useRef, useState, type DragEvent } from 'react'

interface Props {
  onFile: (file: File) => void
  onSample: () => void
  disabled: boolean
}

export function FileUpload({ onFile, onSample, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file && !disabled) onFile(file)
  }

  return (
    <div
      className={`dropzone${dragging ? ' dragging' : ''}`}
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
    >
      <p className="dropzone-title">Drop your bank statement here</p>
      <p className="muted">PDF statement or CSV export. Your file is analyzed and not stored.</p>
      <div className="dropzone-actions">
        <button type="button" className="btn primary" disabled={disabled} onClick={() => inputRef.current?.click()}>
          Choose file
        </button>
        <button type="button" className="btn" disabled={disabled} onClick={onSample}>
          Try sample data
        </button>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,text/csv,.pdf,application/pdf"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onFile(file)
          e.target.value = '' // allow re-selecting the same file
        }}
      />
    </div>
  )
}
