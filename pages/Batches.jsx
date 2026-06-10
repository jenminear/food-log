import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getBatch, modifyBatch, addBatchNote, createBatch } from './api.js'

export default function Batches() {
  const { id } = useParams()
  const [q, setQ]           = useState('')
  const [batch, setBatch]   = useState(null)
  const [error, setError]   = useState(null)
  const [note,  setNote]    = useState('')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg]       = useState(null)

  useEffect(() => {
    if (id) {
      getBatch(id).then(setBatch).catch(e => setError(e.message))
    }
  }, [id])

  async function handleSearch() {
    if (!q.trim()) return
    setSaving(true); setError(null)
    try {
      const data = await createBatch(q)
      if (data.status === 'created') setBatch(data)
      else if (data.status === 'ambiguous') {
        setMsg(`Ambiguous — did you mean: ${data.candidates?.map(c => c.recipe_name).join(', ')}?`)
      } else {
        setMsg('No matching recipe found.')
      }
    } catch(e) { setError(e.message) }
    finally { setSaving(false) }
  }

  async function handleAddNote() {
    if (!note.trim() || !batch) return
    setSaving(true)
    try {
      await addBatchNote(batch.batch_id, note)
      setNote(''); setMsg('Note saved.')
    } catch(e) { setError(e.message) }
    finally { setSaving(false) }
  }

  async function handleRemove(component_id) {
    setSaving(true)
    try {
      const data = await modifyBatch(batch.batch_id, { action:'remove', component_id })
      setBatch(data)
    } catch(e) { setError(e.message) }
    finally { setSaving(false) }
  }

  return (
    <>
      <div className="page-header">
        <span className="page-title">Batches</span>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {msg   && <div className="alert alert-success">{msg}</div>}

      {!batch && (
        <div className="card">
          <h2 style={{marginBottom:'1rem'}}>Start a New Batch</h2>
          <div className="form-row" style={{alignItems:'flex-end'}}>
            <div className="form-group" style={{margin:0}}>
              <label>Search for a recipe</label>
              <input type="text" value={q} onChange={e => setQ(e.target.value)}
                     placeholder="e.g. Veggie Bowl" />
            </div>
            <button className="btn btn-primary" onClick={handleSearch} disabled={saving}>
              {saving ? <span className="spinner"/> : 'Cook'}
            </button>
          </div>
        </div>
      )}

      {batch && (
        <>
          <div className="card">
            <div className="card-header">
              <h2>{batch.recipe_name || `Batch #${batch.batch_id}`}</h2>
              <span className="text-faint text-sm">{batch.batch_date}</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Ingredient</th>
                    <th>Qty</th>
                    <th>Unit</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {batch.components?.map((c, i) => (
                    <tr key={i}>
                      <td>{c.ingredient_name}</td>
                      <td className="mono">{c.quantity_multiple}</td>
                      <td className="mono">{c.portion_unit}</td>
                      <td>
                        <button className="btn btn-ghost text-sm"
                                onClick={() => handleRemove(c.component_id)}>
                          ✕
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <h2 style={{marginBottom:'0.75rem'}}>Add Note</h2>
            <div className="form-row" style={{alignItems:'flex-end'}}>
              <div className="form-group" style={{margin:0}}>
                <input type="text" value={note} onChange={e => setNote(e.target.value)}
                       placeholder="e.g. Used less salt" />
              </div>
              <button className="btn btn-secondary" onClick={handleAddNote} disabled={saving}>
                Save
              </button>
            </div>
          </div>
        </>
      )}
    </>
  )
}
