import { useState } from 'react'

export default function Settings() {
  const [key, setKey] = useState(() => localStorage.getItem('food_log_api_key') || '')
  const [saved, setSaved] = useState(false)

  function save() {
    localStorage.setItem('food_log_api_key', key.trim())
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  function clear() {
    localStorage.removeItem('food_log_api_key')
    setKey('')
    setSaved(false)
  }

  return (
    <div>
      <h2 style={{ marginBottom: '1.5rem' }}>Settings</h2>
      <div className="card" style={{ maxWidth: '480px' }}>
        <h3 style={{ marginBottom: '0.75rem', fontSize: '1rem' }}>API Key</h3>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-faint)', marginBottom: '1rem' }}>
          Required to access the app. Ask the admin for your key.
        </p>
        <div className="form-group">
          <input
            type="password"
            placeholder="Paste your API key here"
            value={key}
            onChange={e => { setKey(e.target.value); setSaved(false) }}
          />
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
          <button className="btn-primary" onClick={save} disabled={!key.trim()}>
            {saved ? 'Saved!' : 'Save'}
          </button>
          {key && (
            <button className="btn-secondary" onClick={clear}>
              Clear
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
