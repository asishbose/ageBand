import { useState, type KeyboardEvent } from 'react'

interface Props {
  onSend: (text: string) => void
  disabled?: boolean
}

export function ChatInput({ onSend, disabled = false }: Props) {
  const [value, setValue] = useState('')

  const submit = () => {
    const trimmed = value.trim()
    if (!trimmed) return
    onSend(trimmed)
    setValue('')
  }

  const handleKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="chat-input-row">
      <input
        className="chat-input"
        type="text"
        placeholder="Type a message…"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKey}
        disabled={disabled}
        aria-label="Chat message"
      />
      <button
        className="btn btn-send"
        onClick={submit}
        disabled={disabled || !value.trim()}
      >
        Send
      </button>
    </div>
  )
}
