import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { searchRecipes, createRecipe, finishRecipe,
         addRecipeIngredient, confirmRecipeIngredient } from './api.js'

export default function Recipes() {
  const navigate = useNavigate()
  const [q, setQ]           = useState('')
  const [results, setResults] = useState([])
  const [error, setError]   = useState(null)

  // New recipe form
  const [showForm, setShowForm]     = useState(false)
  const [recipeName, setRecipeName] = useState('')
  const [session, setSession]       = useState(null)  // {session_key, recipe_id}
  const [ingredient, setIngredient] = useState('')
  const [qty, setQty]               = useState('1')
  const [ingStatus, setIngStatus]   = useState(null)  // result from API
  const [saving, setSaving]         = useState(false)

  useEffect(() => {
    if (q.trim().length < 2) { setResults([]); return }
    searchRecipes(q).then(setResults).catch(() => setResults([]))
  }, [q])

  async function handleCreateRecipe() {
    if (!recipeName.trim()) return
    setSaving(true); setError(null)
    try {
      const data = await createRecipe({ recipe_name: recipeName })
      setSession(data)
    } catch(e) { setError(e.message) }
    finally { setSaving(false) }
  }

  async function handleAddIngredient() {
    if (!ingredient.trim() || !session) return
    setSaving(true); setIngStatus(null)
    try {
      const data = await addRecipeIngredient(session.session_key, {
        ingredient_name: ingredient, quantity_multiple: parseFloat(qty) || 1
      })
      setIngStatus(data)
      if (data.status === 'added') { setIngredient(''); setQty('1') }
    } catch(e) { setError(e.message) }
    finally { setSaving(false) }
  }

  async function handleConfirm(choice) {
    if (!ingStatus?.pending_key) return
    setSaving(true)
    try {
      const data = await confirmRecipeIngredient(session.session_key, {
        pending_key: ingStatus.pending_key, choice
      })
      setIngStatus(data)
      if (data.status === 'added') { setIngredient(''); setQty('1'); setIngStatus(null) }
    } catch(e) { setError(e.message) }
    finally { setSaving(false) }
  }

  async function handleFinish() {
    if (!session) return
    setSaving(true)
    try {
      await finishRecipe(session.session_key)
      setSession(null); setShowForm(false); setRecipeName('')
      navigate(`/recipes/${session.recipe_id}`)
    } catch(e) { setError(e.message) }
    finally { setSaving(false) }
  }

  return (
    <>
      <div className="page-header">
        <span className="page-title">Recipes</span>
        <button className="btn btn-primary" onClick={() => setShowForm(v => !v)}>
          + New Recipe
        </button>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {showForm && !session && (
        <div className="card">
          <h2 style={{marginBottom:'1rem'}}>New Recipe</h2>
          <div className="form-group">
            <label>Recipe Name</label>
            <input type="text" value={recipeName} onChange={e => setRecipeName(e.target.value)}
                   placeholder="e.g. Veggie Bowl" />
          </div>
          <button className="btn btn-primary" onClick={handleCreateRecipe} disabled={saving}>
            Create &amp; Add Ingredients
          </button>
        </div>
      )}

      {session && (
        <div className="card">
          <div className="card-header">
            <h2>Adding ingredients to: {recipeName}</h2>
            <button className="btn btn-primary" onClick={handleFinish} disabled={saving}>
              Finish Recipe
            </button>
          </div>

          {ingStatus?.status === 'needs_confirmation' && (
            <div className="alert alert-warn" style={{marginBottom:'1rem'}}>
              Low confidence — pick a match:
              <div className="candidate-list mt-1">
                {ingStatus.candidates?.map((c, i) => (
                  <div key={i} className="candidate-item" onClick={() => handleConfirm(i+1)}>
                    <span className="candidate-num">{i+1}</span>
                    <div>
                      <div className="candidate-name">{c.ingredient_name}</div>
                      <div className="candidate-meta">{c.calories} kcal · {c.portion_amount} {c.portion_unit}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="form-row" style={{alignItems:'flex-end'}}>
            <div className="form-group" style={{margin:0}}>
              <label>Ingredient</label>
              <input type="text" value={ingredient} onChange={e => setIngredient(e.target.value)}
                     placeholder="e.g. rolled oats" />
            </div>
            <div className="form-group" style={{margin:0, maxWidth:'7rem'}}>
              <label>Qty ×</label>
              <input type="number" value={qty} onChange={e => setQty(e.target.value)} min="0.1" step="0.1" />
            </div>
            <button className="btn btn-secondary" onClick={handleAddIngredient} disabled={saving}>
              Add
            </button>
          </div>
          {ingStatus?.status === 'added' && (
            <div className="alert alert-success mt-1">✓ {ingStatus.ingredient_name} added</div>
          )}
        </div>
      )}

      <div className="card">
        <div className="form-group" style={{margin:0}}>
          <input type="text" value={q} onChange={e => setQ(e.target.value)}
                 placeholder="Search recipes…" />
        </div>
      </div>

      {results.length === 0 && q.length >= 2 && (
        <div className="empty">No recipes found.</div>
      )}
      {results.map(r => (
        <div className="card" key={r.recipe_id} style={{cursor:'pointer'}}
             onClick={() => navigate(`/recipes/${r.recipe_id}`)}>
          <div className="card-header">
            <strong>{r.recipe_name}</strong>
            <div className="btn-group">
              {r.vegan      && <span className="badge badge-green">vegan</span>}
              {r.vegetarian && <span className="badge badge-green">veggie</span>}
            </div>
          </div>
          <span className="text-faint text-sm">{r.num_servings} servings</span>
        </div>
      ))}
    </>
  )
}
