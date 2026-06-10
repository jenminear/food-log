import { useState } from 'react'
import { getRangeNutrition } from './api.js'
import { NutGrid } from '../components/NutGrid.jsx'

function daysAgo(n) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

export default function Reports() {
  const today = new Date().toISOString().slice(0, 10)
  const [start, setStart] = useState(daysAgo(6))
  const [end,   setEnd]   = useState(today)
  const [data,  setData]  = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  function load() {
    setLoading(true); setError(null)
    getRangeNutrition(start, end)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }

  return (
    <>
      <div className="page-header">
        <span className="page-title">Reports</span>
      </div>

      <div className="card">
        <div className="form-row" style={{alignItems:'flex-end'}}>
          <div className="form-group" style={{margin:0}}>
            <label>Start date</label>
            <input type="date" value={start} onChange={e => setStart(e.target.value)} />
          </div>
          <div className="form-group" style={{margin:0}}>
            <label>End date</label>
            <input type="date" value={end} onChange={e => setEnd(e.target.value)} />
          </div>
          <button className="btn btn-primary" onClick={load} disabled={loading}>
            {loading ? <span className="spinner"/> : 'Load'}
          </button>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {data && (
        <>
          <div className="card">
            <div className="card-header">
              <h2>Totals — {data.num_days} days, {data.num_meals} meals</h2>
            </div>
            <NutGrid data={data.totals} />
          </div>
          <div className="card">
            <div className="card-header">
              <h2>Daily Averages</h2>
            </div>
            <NutGrid data={data.daily_averages} />
          </div>
        </>
      )}
    </>
  )
}
