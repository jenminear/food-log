import { useEffect, useState } from 'react'
import { browseIngredients, browseIngredientsByLetter, createIngredient, updateIngredient, deleteIngredient } from './api.js'

const NUTRITION_FIELDS = [
  { key: 'calories',      label: 'Calories', step: '1'   },
  { key: 'protein_grams', label: 'Protein (g)', step: '0.1' },
  { key: 'fat_grams',     label: 'Fat (g)',     step: '0.1' },
  { key: 'carb_grams',    label: 'Carbs (g)',   step: '0.1' },
  { key: 'fiber_grams',   label: 'Fiber (g)',   step: '0.1' },
]

const EMPTY_FORM = {
  ingredient_name: '',
  portion_unit: 'g',
  portion_grams: '100',
  calories: '',
  protein_grams: '',
  fat_grams: '',
  carb_grams: '',
  fiber_grams: '',
  nutrition_info_source: '',
}

const AZ_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ#'.split('')

// Convert per-100g DB value → per-portion display value
function toPortionDisplay(per100g, portionGrams) {
  if (per100g == null || per100g === '') return ''
  return ((parseFloat(per100g) * parseFloat(portionGrams)) / 100).toFixed(2).replace(/\.?0+$/, '')
}
// Convert per-portion display value → per-100g for storage
function fromPortionDisplay(perPortion, portionGrams) {
  if (perPortion === '' || perPortion == null) return null
  const g = parseFloat(portionGrams)
  if (!g) return null
  return parseFloat(perPortion) / g * 100
}

export default function Ingredients() {
  const [q, setQ] = useState('')
  const [results, setResults] = useState([])
  const [error, setError] = useState(null)
  const [searched, setSearched] = useState(false)

  // A-Z browse
  const [azLetter, setAzLetter] = useState(null)
  const [azResults, setAzResults] = useState([])

  const [showAddForm, setShowAddForm] = useState(false)
  const [addForm, setAddForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)

  const [editingIngredient, setEditingIngredient] = useState(null)
  const [editForm, setEditForm] = useState(null)
  const [savingEdit, setSavingEdit] = useState(false)
  const [deletingId, setDeletingId] = useState(null)

  useEffect(() => {
    if (q.trim().length < 2) { setResults([]); setSearched(false); return }
    setAzLetter(null)
    browseIngredients(q.trim())
      .then(r => { setResults(r); setSearched(true) })
      .catch(() => { setResults([]); setSearched(true) })
  }, [q])

  useEffect(() => {
    if (azLetter == null) { setAzResults([]); return }
    setQ('')
    browseIngredientsByLetter(azLetter).then(setAzResults).catch(() => setAzResults([]))
  }, [azLetter])

  function refreshSearch() {
    if (azLetter != null) {
      browseIngredientsByLetter(azLetter).then(setAzResults).catch(() => {})
    } else if (q.trim().length >= 2) {
      browseIngredients(q.trim()).then(setResults).catch(() => {})
    }
  }

  async function handleCreate() {
    if (!addForm.ingredient_name.trim() || !addForm.portion_unit.trim()) return
    setSaving(true)
    setError(null)
    try {
      const portionG = parseFloat(addForm.portion_grams) || 100
      const toP100 = v => fromPortionDisplay(v, portionG)
      await createIngredient({
        ingredient_name: addForm.ingredient_name.trim(),
        portion_unit: addForm.portion_unit.trim(),
        portion_grams: portionG,
        calories:      toP100(addForm.calories),
        protein_grams: toP100(addForm.protein_grams),
        fat_grams:     toP100(addForm.fat_grams),
        carb_grams:    toP100(addForm.carb_grams),
        fiber_grams:   toP100(addForm.fiber_grams),
        nutrition_info_source: addForm.nutrition_info_source.trim() || null,
      })
      setShowAddForm(false)
      setAddForm(EMPTY_FORM)
      refreshSearch()
    } catch (e) {
      setError('Failed to add ingredient: ' + e.message)
    } finally {
      setSaving(false)
    }
  }

  function openEditModal(ingredient) {
    setEditingIngredient(ingredient)
    const g = ingredient.portion_grams || 100
    setEditForm({
      ingredient_name: ingredient.ingredient_name,
      portion_unit: ingredient.portion_unit,
      portion_grams: String(g),
      calories:      toPortionDisplay(ingredient.calories, g),
      protein_grams: toPortionDisplay(ingredient.protein_grams, g),
      fat_grams:     toPortionDisplay(ingredient.fat_grams, g),
      carb_grams:    toPortionDisplay(ingredient.carb_grams, g),
      fiber_grams:   toPortionDisplay(ingredient.fiber_grams, g),
      nutrition_info_source: ingredient.nutrition_info_source ?? '',
    })
  }

  function closeEditModal() {
    setEditingIngredient(null)
    setEditForm(null)
  }

  async function saveEdit() {
    if (!editingIngredient || !editForm) return
    setSavingEdit(true)
    setError(null)
    try {
      const portionG = parseFloat(editForm.portion_grams) || 100
      const toP100 = v => fromPortionDisplay(v, portionG)
      await updateIngredient(editingIngredient.ingredient_id, {
        ingredient_name: editForm.ingredient_name,
        portion_unit: editForm.portion_unit,
        portion_grams: portionG,
        calories:      toP100(editForm.calories),
        protein_grams: toP100(editForm.protein_grams),
        fat_grams:     toP100(editForm.fat_grams),
        carb_grams:    toP100(editForm.carb_grams),
        fiber_grams:   toP100(editForm.fiber_grams),
        nutrition_info_source: editForm.nutrition_info_source.trim() || null,
      })
      closeEditModal()
      refreshSearch()
    } catch (e) {
      setError('Failed to save changes: ' + e.message)
    } finally {
      setSavingEdit(false)
    }
  }

  async function handleDelete(ingredient) {
    if (!confirm(`Delete "${ingredient.ingredient_name}"? This cannot be undone.`)) return
    setDeletingId(ingredient.ingredient_id)
    setError(null)
    try {
      await deleteIngredient(ingredient.ingredient_id)
      refreshSearch()
    } catch (e) {
      setError('Failed to delete: ' + e.message)
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <>
      <div className="page-header">
        <span className="page-title">Ingredients</span>
        <button className="btn btn-primary" onClick={() => setShowAddForm(v => !v)}>
          + Add Ingredient
        </button>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {showAddForm && (
        <div className="card">
          <h2 style={{marginBottom:'1rem'}}>Add a Standalone Ingredient</h2>
          <p className="text-sm text-faint" style={{marginBottom:'1rem'}}>
            For things you already have nutrition info for (a package label, a homemade
            item) — no USDA/OFF lookup happens here.
          </p>
          <div className="form-group">
            <label>Ingredient Name <span style={{color:'red'}}>*</span></label>
            <input type="text" value={addForm.ingredient_name}
              onChange={e => setAddForm({...addForm, ingredient_name: e.target.value})}
              placeholder="e.g. ice cream sandwich" />
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>Portion Unit <span style={{color:'red'}}>*</span></label>
              <input type="text" value={addForm.portion_unit}
                onChange={e => setAddForm({...addForm, portion_unit: e.target.value})}
                placeholder='e.g. "1 sandwich" or "g"' />
            </div>
            <div className="form-group">
              <label>Portion Grams</label>
              <input type="number" step="0.1" value={addForm.portion_grams}
                onChange={e => setAddForm({...addForm, portion_grams: e.target.value})} />
            </div>
          </div>
          <p className="text-sm text-faint" style={{marginBottom:'0.5rem'}}>
            Nutrition values per 1 portion{addForm.portion_grams ? ` (${addForm.portion_grams}g)` : ''} (optional):
          </p>
          <div className="form-row-3">
            {NUTRITION_FIELDS.map(f => (
              <div className="form-group" key={f.key}>
                <label>{f.label}</label>
                <input type="number" step={f.step} value={addForm[f.key]}
                  onChange={e => setAddForm({...addForm, [f.key]: e.target.value})} />
              </div>
            ))}
          </div>
          <div className="form-group">
            <label>Nutrition Info Source</label>
            <input type="text" value={addForm.nutrition_info_source}
              onChange={e => setAddForm({...addForm, nutrition_info_source: e.target.value})}
              placeholder="e.g. Package label" />
          </div>
          <div style={{display:'flex', gap:'0.5rem'}}>
            <button className="btn btn-primary" onClick={handleCreate}
              disabled={saving || !addForm.ingredient_name.trim() || !addForm.portion_unit.trim()}>
              {saving ? 'Saving…' : 'Save Ingredient'}
            </button>
            <button className="btn btn-secondary" onClick={() => { setShowAddForm(false); setAddForm(EMPTY_FORM) }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Search bar */}
      <div className="card" style={{marginBottom:'0.75rem'}}>
        <div className="form-group" style={{margin:0}}>
          <input type="text" value={q} onChange={e => { setQ(e.target.value); setAzLetter(null) }}
                 placeholder="Search ingredients…" />
        </div>
      </div>

      {/* A-Z letter panel */}
      <div className="card" style={{padding:'0.5rem', marginBottom:'0.75rem'}}>
        <div style={{display:'flex', flexWrap:'wrap', gap:'2px'}}>
          {AZ_LETTERS.map(l => (
            <button key={l} onClick={() => setAzLetter(azLetter === l ? null : l)}
              style={{
                minWidth:'28px', padding:'0.2rem 0.3rem', border:'1px solid var(--border)',
                borderRadius:'4px', background: azLetter === l ? 'var(--accent)' : 'transparent',
                color: azLetter === l ? '#fff' : 'var(--text)', cursor:'pointer', fontSize:'0.8rem',
              }}>
              {l}
            </button>
          ))}
        </div>
      </div>

      {searched && !azLetter && results.length === 0 && (
        <div className="empty">No ingredients found.</div>
      )}

      {(() => {
        const displayRows = azLetter ? azResults : results
        if (displayRows.length === 0) return null
        return (
          <div className="card">
            {azLetter && (
              <div className="card-header" style={{marginBottom:'0.75rem'}}>
                <h3 style={{margin:0}}>{azLetter === '#' ? 'Other' : azLetter}</h3>
                <span className="text-faint text-sm">{displayRows.length} ingredient{displayRows.length !== 1 ? 's' : ''}</span>
              </div>
            )}
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th style={{textAlign:'left'}}>Ingredient</th>
                    <th style={{textAlign:'left'}}>Portion</th>
                    <th>kcal</th>
                    <th>Protein</th>
                    <th>Fat</th>
                    <th>Carbs</th>
                    <th>Fiber</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {displayRows.map(r => {
                    const g = r.portion_grams || 100
                    return (
                      <tr key={r.ingredient_id}>
                        <td style={{textAlign:'left'}}>
                          <button
                            className="link-btn"
                            style={{background:'none', border:'none', padding:0, color:'var(--accent)', cursor:'pointer', textDecoration:'underline', textAlign:'left', display:'block', width:'100%'}}
                            onClick={() => openEditModal(r)}
                          >
                            {r.ingredient_name}
                          </button>
                          {r.data_quality_warning && (
                            <div className="text-sm" style={{color:'var(--warn, #b8860b)'}}>⚠ {r.data_quality_warning}</div>
                          )}
                        </td>
                        <td style={{textAlign:'left'}} className="mono">{r.portion_unit} ({g}g)</td>
                        <td className="mono">{toPortionDisplay(r.calories, g) || '—'}</td>
                        <td className="mono">{toPortionDisplay(r.protein_grams, g) || '—'}</td>
                        <td className="mono">{toPortionDisplay(r.fat_grams, g) || '—'}</td>
                        <td className="mono">{toPortionDisplay(r.carb_grams, g) || '—'}</td>
                        <td className="mono">{toPortionDisplay(r.fiber_grams, g) || '—'}</td>
                        <td>
                          <button
                            className="btn btn-secondary"
                            style={{padding:'0.25rem 0.5rem', fontSize:'0.875rem'}}
                            onClick={() => handleDelete(r)}
                            disabled={deletingId === r.ingredient_id}
                          >
                            {deletingId === r.ingredient_id ? '…' : 'Delete'}
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )
      })()}

      {editingIngredient && editForm && (
        <div className="modal-overlay" onClick={closeEditModal}>
          <div className="modal-content" onClick={e => e.stopPropagation()} style={{maxWidth:'650px'}}>
            <h3>Edit Ingredient</h3>

            <div className="form-group">
              <label>Ingredient Name</label>
              <input type="text" value={editForm.ingredient_name}
                onChange={e => setEditForm({...editForm, ingredient_name: e.target.value})} />
            </div>

            <div className="form-row">
              <div className="form-group">
                <label>Portion Unit</label>
                <input type="text" value={editForm.portion_unit}
                  onChange={e => setEditForm({...editForm, portion_unit: e.target.value})} />
              </div>
              <div className="form-group">
                <label>Portion Grams</label>
                <input type="number" step="0.1" value={editForm.portion_grams}
                  onChange={e => setEditForm({...editForm, portion_grams: e.target.value})} />
              </div>
            </div>

            <p className="text-sm text-faint" style={{marginBottom:'0.5rem'}}>
              Per 1 portion{editForm.portion_grams ? ` (${editForm.portion_grams}g)` : ''}:
            </p>
            <div className="form-row-3">
              {NUTRITION_FIELDS.map(f => (
                <div className="form-group" key={f.key}>
                  <label>{f.label}</label>
                  <input type="number" step={f.step} value={editForm[f.key]}
                    onChange={e => setEditForm({...editForm, [f.key]: e.target.value})} />
                </div>
              ))}
            </div>

            <div className="form-group">
              <label>Nutrition Info Source</label>
              <input type="text" value={editForm.nutrition_info_source}
                onChange={e => setEditForm({...editForm, nutrition_info_source: e.target.value})} />
            </div>

            <div className="divider"></div>

            <div style={{display:'flex', gap:'0.5rem'}}>
              <button className="btn btn-primary" onClick={saveEdit} disabled={savingEdit}>
                {savingEdit ? 'Saving…' : 'Save Changes'}
              </button>
              <button className="btn btn-secondary" onClick={closeEditModal}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
