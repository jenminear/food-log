import { useState } from 'react'
import { startMeal, selectRecipeForMeal, finishMeal, addMealNote } from './api.js'
import { useNavigate } from 'react-router-dom'

export default function LogMeal() {
  const navigate  = useNavigate()
  const today     = new Date().toISOString().slice(0, 10)
  const [step, setStep]       = useState('start')   // start | pick | done
  const [mealType, setMealType] = useState('lunch')
  const [mealDate, setMealDate] = useState(today)
  const [query, setQuery]     = useState('')
  const [session, setSession] = useState(null)
  const [recipes, setRecipes] = useState([])
  const [note, setNote]       = useState('')
  const [error, setError]     = useState(null)
  const [saving, setSaving]   = useState(false)
  const [done, setDone]       = useState(null)

  async function handleStart() {
    if (!query.trim()) return
    setSaving(true); setError(null)
    try {
      const data = await startMeal({ meal_type: mealType, query, meal_date: mealDate })
      setSession(data)
      setRecipes(data.recipes || [])
      setStep('pick')
    } catch(e) { setError(e.message) }
    finally { setSaving(false) }
  }

  async function handleSelectRecipe(recipe_id) {
    setSaving(true); setError(null)
    try {
      const data = await selectRecipeForMeal({
        session_key: session.session_key,
        recipe_id,
        fraction_of_batch: 1.0,
      })
      if (data.status === 'no_batch') {
        setError('No batch found for this recipe. Cook a batch first!')
        return
      }
      const finished = await finishMeal(session.session_key)
      setDone(finished); setStep('done')
    } catch(e) { setError(e.message) }
    finally { setSaving(false) }
  }

  async function handleAddNote() {
    if (!note.trim() || !session) return
    setSaving(true)
    try {
      await addMealNote(session.session_key, note)
      setNote('')
    } catch(e) { setError(e.message) }
    finally { setSaving(false) }
  }

  if (step === 'done') return (
    <>
      <div className="page-header"><span className="page-title">Meal Logged ✓</span></div>
      <div className="alert alert-success">Meal recorded successfully!</div>
      <div className="btn-group">
        <button className="btn btn-primary" onClick={() => navigate('/')}>View Today</button>
        <button className="btn btn-secondary" onClick={() => {
          setStep('start'); setQuery(''); setSession(null); setDone(null)
        }}>Log Another</button>
      </div>
    </>
  )

  return (
    <>
      <div className="page-header"><span className="page-title">Log a Meal</span></div>

      {error && <div className="alert alert-error">{error}</div>}

      {step === 'start' && (
        <div className="card">
          <div className="form-group">
            <label>Meal Type</label>
            <select value={mealType} onChange={e => setMealType(e.target.value)}>
              <option value="breakfast">Breakfast</option>
              <option value="lunch">Lunch</option>
              <option value="dinner">Dinner</option>
              <option value="snack">Snack</option>
            </select>
          </div>
          <div className="form-group">
            <label>Date</label>
            <input type="date" value={mealDate} onChange={e => setMealDate(e.target.value)} />
          </div>
          <div className="form-group">
            <label>What did you eat?</label>
            <input type="text" value={query} onChange={e => setQuery(e.target.value)}
                   placeholder="e.g. veggie bowl, oatmeal…" />
          </div>
          <button className="btn btn-primary" onClick={handleStart} disabled={saving}>
            {saving ? <span className="spinner"/> : 'Search →'}
          </button>
        </div>
      )}

      {step === 'pick' && (
        <div className="card">
          <h2 style={{marginBottom:'1rem'}}>Select a Recipe</h2>
          {recipes.length === 0
            ? <div className="empty">No matching recipes found.</div>
            : recipes.map(r => (
              <div key={r.recipe_id} className="candidate-item mb-1"
                   onClick={() => handleSelectRecipe(r.recipe_id)}>
                <div>
                  <div className="candidate-name">{r.recipe_name}</div>
                  <div className="candidate-meta">{r.num_servings} servings</div>
                </div>
              </div>
            ))
          }
          <hr className="divider"/>
          <div className="form-row" style={{alignItems:'flex-end'}}>
            <div className="form-group" style={{margin:0}}>
              <label>Add a note</label>
              <input type="text" value={note} onChange={e => setNote(e.target.value)}
                     placeholder="Optional note…" />
            </div>
            <button className="btn btn-secondary" onClick={handleAddNote} disabled={saving}>Save Note</button>
          </div>
        </div>
      )}
    </>
  )
}
