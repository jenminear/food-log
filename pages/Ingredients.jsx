import { useEffect, useState } from 'react'
import { browseIngredients, createIngredient, updateIngredient, deleteIngredient } from './api.js'

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

export default function Ingredients() {
  const [q, setQ] = useState('')
  const [results, setResults] = useState([])
  const [error, setError] = useState(null)
  const [searched, setSearched] = useState(false)

  const [showAddForm, setShowAddForm] = useState(false)
  const [addForm, setAddForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)

  const [editingIngredient, setEditingIngredient] = useState(null)
  const [editForm, setEditForm] = useState(null)
  const [savingEdit, setSavingEdit] = useState(false)
  const [deletingId, setDeletingId] = useState(null)

  useEffect(() => {
    if (q.trim().length < 2) { setResults([]); setSearched(false); return }
    browseIngredients(q.trim())
      .then(r => { setResults(r); setSearched(true) })
      .catch(() => { setResults([]); setSearched(true) })
  }, [q])

  function refreshSearch() {
    if (q.trim().length >= 2) {
      browseIngredients(q.trim()).then(setResults).catch(() => {})
    }
  }

  async function handleCreate() {
    if (!addForm.ingredient_name.trim() || !addForm.portion_unit.trim()) return
    setSaving(true)
    setError(null)
    try {
      await createIngredient({
        ingredient_name: addForm.ingredient_name.trim(),
        portion_unit: addForm.portion_unit.trim(),
        portion_grams: parseFloat(addForm.portion_grams) || 100,
        calories: addForm.calories === '' ? null : parseFloat(addForm.calories),
        protein_grams: addForm.protein_grams === '' ? null : parseFloat(addForm.protein_grams),
        fat_grams: addForm.fat_grams === '' ? null : parseFloat(addForm.fat_grams),
        carb_grams: addForm.carb_grams === '' ? null : parseFloat(addForm.carb_grams),
        fiber_grams: addForm.fiber_grams === '' ? null : parseFloat(addForm.fiber_grams),
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
    setEditForm({
      ingredient_name: ingredient.ingredient_name,
      portion_unit: ingredient.portion_unit,
      portion_grams: ingredient.portion_grams,
      calories: ingredient.calories ?? '',
      protein_grams: ingredient.protein_grams ?? '',
      fat_grams: ingredient.fat_grams ?? '',
      carb_grams: ingredient.carb_grams ?? '',
      fiber_grams: ingredient.fiber_grams ?? '',
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
      await updateIngredient(editingIngredient.ingredient_id, {
        ingredient_name: editForm.ingredient_name,
        portion_unit: editForm.portion_unit,
        portion_grams: parseFloat(editForm.portion_grams),
        calories: editForm.calories === '' ? null : parseFloat(editForm.calories),
        protein_grams: editForm.protein_grams === '' ? null : parseFloat(editForm.protein_grams),
        fat_grams: editForm.fat_grams === '' ? null : parseFloat(editForm.fat_grams),
        carb_grams: editForm.carb_grams === '' ? null : parseFloat(editForm.carb_grams),
        fiber_grams: editForm.fiber_grams === '' ? null : parseFloat(editForm.fiber_grams),
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
          <p className="text-sm text-faint" style={{marginBottom:'0.5rem'}}>Nutrition values, per 100g:</p>
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

      <div className="card">
        <div className="form-group" style={{margin:0}}>
          <input type="text" value={q} onChange={e => setQ(e.target.value)}
                 placeholder="Search ingredients…" />
        </div>
      </div>

      {searched && results.length === 0 && (
        <div className="empty">No ingredients found.</div>
      )}

      {results.length > 0 && (
        <div className="card">
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
                {results.map(r => (
                  <tr key={r.ingredient_id}>
                    <td style={{textAlign:'left'}}>
                      <button
                        className="link-btn"
                        style={{background:'none', border:'none', padding:0, color:'var(--accent)', cursor:'pointer', textDecoration:'underline'}}
                        onClick={() => openEditModal(r)}
                      >
                        {r.ingredient_name}
                      </button>
                      {r.data_quality_warning && (
                        <div className="text-sm" style={{color:'var(--warn, #b8860b)'}}>⚠ {r.data_quality_warning}</div>
                      )}
                    </td>
                    <td style={{textAlign:'left'}} className="mono">{r.portion_unit} ({r.portion_grams}g)</td>
                    <td className="mono">{r.calories ?? '—'}</td>
                    <td className="mono">{r.protein_grams ?? '—'}</td>
                    <td className="mono">{r.fat_grams ?? '—'}</td>
                    <td className="mono">{r.carb_grams ?? '—'}</td>
                    <td className="mono">{r.fiber_grams ?? '—'}</td>
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
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

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

            <p className="text-sm text-faint" style={{marginBottom:'0.5rem'}}>Per 100g:</p>
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
