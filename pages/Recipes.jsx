import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { searchRecipes, createRecipe, finishRecipe, updateRecipe, extractRecipeFromUrl, extractRecipeFromImage } from './api.js'

export default function Recipes() {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [results, setResults] = useState([])
  const [error, setError] = useState(null)

  // New recipe form - basic fields
  const [showForm, setShowForm] = useState(false)
  const [recipeName, setRecipeName] = useState('')
  const [numServings, setNumServings] = useState('')
  const [activeHours, setActiveHours] = useState('0')
  const [activeMins, setActiveMins] = useState('0')
  const [totalHours, setTotalHours] = useState('0')
  const [totalMins, setTotalMins] = useState('0')
  const [needOven, setNeedOven] = useState(false)
  const [vegetarian, setVegetarian] = useState(false)
  const [vegan, setVegan] = useState(false)

  // URL and Picture modals
  const [showUrlModal, setShowUrlModal] = useState(false)
  const [showPictureModal, setShowPictureModal] = useState(false)
  const [recipeUrl, setRecipeUrl] = useState('')
  const [recipePicture, setRecipePicture] = useState(null)
  const [extracting, setExtracting] = useState(false)

  // Ingredients/steps extracted via AI, applied after the recipe is created
  const [extractedIngredients, setExtractedIngredients] = useState([])
  const [extractedSteps, setExtractedSteps] = useState([])

  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (q.trim().length < 2) { setResults([]); return }
    searchRecipes(q).then(setResults).catch(() => setResults([]))
  }, [q])

  // Validate URL
  function isValidUrl(string) {
    try {
      const url = new URL(string)
      return url.protocol === 'http:' || url.protocol === 'https:'
    } catch (_) {
      return false
    }
  }

  // Apply AI-extracted recipe data to the New Recipe form
  function applyExtracted(extracted) {
    if (extracted.recipe_name) setRecipeName(extracted.recipe_name)
    if (extracted.num_servings) setNumServings(String(extracted.num_servings))
    if (extracted.active_time_mins != null) {
      setActiveHours(String(Math.floor(extracted.active_time_mins / 60)))
      setActiveMins(String(extracted.active_time_mins % 60))
    }
    if (extracted.total_time_mins != null) {
      setTotalHours(String(Math.floor(extracted.total_time_mins / 60)))
      setTotalMins(String(extracted.total_time_mins % 60))
    }
    setNeedOven(!!extracted.need_oven)
    setVegetarian(!!extracted.vegetarian)
    setVegan(!!extracted.vegan)
    setExtractedIngredients(extracted.ingredients || [])
    setExtractedSteps(extracted.steps || [])
    setShowForm(true)
  }

  async function handleUrlSubmit() {
    if (!isValidUrl(recipeUrl)) {
      setError('Please enter a valid URL starting with http:// or https://')
      return
    }
    setExtracting(true)
    setError(null)
    try {
      const extracted = await extractRecipeFromUrl(recipeUrl)
      applyExtracted(extracted)
      setShowUrlModal(false)
    } catch (e) {
      setError('Failed to extract recipe: ' + e.message)
    } finally {
      setExtracting(false)
    }
  }

  async function handlePictureSubmit() {
    if (!recipePicture) {
      setError('Please select a picture')
      return
    }
    setExtracting(true)
    setError(null)
    try {
      const extracted = await extractRecipeFromImage(recipePicture)
      applyExtracted(extracted)
      setShowPictureModal(false)
      setRecipePicture(null)
    } catch (e) {
      setError('Failed to extract recipe: ' + e.message)
    } finally {
      setExtracting(false)
    }
  }

  // ========== CREATE RECIPE ==========

  async function handleCreateRecipe() {
    if (!recipeName.trim()) {
      setError('Recipe name is required')
      return
    }

    setSaving(true)
    setError(null)

    try {
      const activeMinsTotal = parseInt(activeHours) * 60 + parseInt(activeMins)
      const totalMinsTotal = parseInt(totalHours) * 60 + parseInt(totalMins)

      const session = await createRecipe({
        recipe_name: recipeName,
        num_servings: numServings ? parseFloat(numServings) : null,
        active_time_mins: activeMinsTotal || null,
        total_time_mins: totalMinsTotal || null,
        need_oven: needOven,
        vegetarian: vegetarian,
        vegan: vegan,
        source: recipeUrl || null
      })

      await finishRecipe(session.session_key)

      if (extractedSteps.length > 0) {
        await updateRecipe(session.recipe_id, {
          recipe_name:      recipeName,
          steps_txt:        JSON.stringify(extractedSteps),
          num_servings:     numServings ? parseFloat(numServings) : null,
          active_time_mins: activeMinsTotal || null,
          total_time_mins:  totalMinsTotal || null,
          need_oven:        needOven,
          vegetarian:       vegetarian,
          vegan:            vegan,
          source:           recipeUrl || null,
        })
      }

      const pendingIngredients = extractedIngredients
      resetForm()
      navigate(`/recipes/${session.recipe_id}`, { state: { pendingIngredients } })
    } catch (e) {
      setError('Failed to create recipe: ' + e.message)
    } finally {
      setSaving(false)
    }
  }

  function resetForm() {
    setShowForm(false)
    setRecipeName('')
    setNumServings('')
    setActiveHours('0')
    setActiveMins('0')
    setTotalHours('0')
    setTotalMins('0')
    setNeedOven(false)
    setVegetarian(false)
    setVegan(false)
    setRecipeUrl('')
    setExtractedIngredients([])
    setExtractedSteps([])
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

      {/* URL Modal */}
      {showUrlModal && (
        <div className="modal-overlay" onClick={() => setShowUrlModal(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()} style={{maxWidth:'700px'}}>
            <h3>Enter Recipe URL</h3>
            <div className="form-group">
              <label>Web Address</label>
              <input
                type="url"
                value={recipeUrl}
                onChange={e => setRecipeUrl(e.target.value)}
                placeholder="https://example.com/recipe"
                style={{width:'100%', padding:'0.75rem', fontSize:'1rem'}}
              />
            </div>
            {extracting && (
              <div className="text-sm text-faint" style={{marginBottom:'0.5rem'}}>
                Extracting recipe… this can take up to 30 seconds.
              </div>
            )}
            <div style={{display:'flex', gap:'0.5rem', justifyContent:'flex-end'}}>
              <button className="btn btn-secondary" onClick={() => setShowUrlModal(false)} disabled={extracting}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handleUrlSubmit} disabled={extracting}>
                {extracting ? 'Extracting…' : 'Extract Recipe'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Picture Modal */}
      {showPictureModal && (
        <div className="modal-overlay" onClick={() => setShowPictureModal(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <h3>Upload Recipe Picture</h3>
            <div className="form-group">
              <label>Select Picture</label>
              <input
                type="file"
                accept="image/*"
                onChange={e => setRecipePicture(e.target.files[0])}
              />
            </div>
            {extracting && (
              <div className="text-sm text-faint" style={{marginBottom:'0.5rem'}}>
                Extracting recipe… this can take up to 30 seconds.
              </div>
            )}
            <div style={{display:'flex', gap:'0.5rem', justifyContent:'flex-end'}}>
              <button className="btn btn-secondary" onClick={() => setShowPictureModal(false)} disabled={extracting}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handlePictureSubmit} disabled={extracting}>
                {extracting ? 'Extracting…' : 'Extract Recipe'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* New Recipe Form */}
      {showForm && (
        <div className="card">
          <h2 style={{marginBottom:'1rem'}}>New Recipe</h2>

          {/* Quick Action Buttons */}
          <div style={{display:'flex', gap:'0.5rem', marginBottom:'1rem'}}>
            <button className="btn btn-secondary" onClick={() => setShowUrlModal(true)}>
              From Web Address
            </button>
            <button className="btn btn-secondary" onClick={() => setShowPictureModal(true)}>
              From Picture
            </button>
          </div>

          {/* Recipe Name */}
          <div className="form-group">
            <label>Recipe Name <span style={{color:'red'}}>*</span></label>
            <input
              type="text"
              value={recipeName}
              onChange={e => setRecipeName(e.target.value)}
              placeholder="e.g. Veggie Bowl"
              required
            />
          </div>

          {/* Number of Servings */}
          <div className="form-group">
            <label>Number of Servings</label>
            <input
              type="number"
              value={numServings}
              onChange={e => setNumServings(e.target.value)}
              placeholder="e.g. 4"
              min="0.1"
              step="0.1"
            />
          </div>

          {/* Active Time */}
          <div className="form-group">
            <label>Active Time</label>
            <div style={{display:'flex', gap:'0.5rem', alignItems:'center'}}>
              <input
                type="number"
                value={activeHours}
                onChange={e => setActiveHours(e.target.value)}
                min="0"
                style={{width:'5rem'}}
              />
              <span>hours</span>
              <input
                type="number"
                value={activeMins}
                onChange={e => setActiveMins(e.target.value)}
                min="0"
                max="59"
                style={{width:'5rem'}}
              />
              <span>minutes</span>
            </div>
          </div>

          {/* Total Time */}
          <div className="form-group">
            <label>Total Time</label>
            <div style={{display:'flex', gap:'0.5rem', alignItems:'center'}}>
              <input
                type="number"
                value={totalHours}
                onChange={e => setTotalHours(e.target.value)}
                min="0"
                style={{width:'5rem'}}
              />
              <span>hours</span>
              <input
                type="number"
                value={totalMins}
                onChange={e => setTotalMins(e.target.value)}
                min="0"
                max="59"
                style={{width:'5rem'}}
              />
              <span>minutes</span>
            </div>
          </div>

          {/* Yes/No Toggles */}
          <div className="form-group">
            <label style={{display:'flex', alignItems:'center', gap:'0.5rem', cursor:'pointer'}}>
              <input
                type="checkbox"
                checked={needOven}
                onChange={e => setNeedOven(e.target.checked)}
                style={{width:'auto'}}
              />
              Needs Oven?
            </label>
          </div>

          <div className="form-group">
            <label style={{display:'flex', alignItems:'center', gap:'0.5rem', cursor:'pointer'}}>
              <input
                type="checkbox"
                checked={vegetarian}
                onChange={e => setVegetarian(e.target.checked)}
                style={{width:'auto'}}
              />
              Vegetarian?
            </label>
          </div>

          <div className="form-group">
            <label style={{display:'flex', alignItems:'center', gap:'0.5rem', cursor:'pointer'}}>
              <input
                type="checkbox"
                checked={vegan}
                onChange={e => setVegan(e.target.checked)}
                style={{width:'auto'}}
              />
              Vegan?
            </label>
          </div>

          {(extractedIngredients.length > 0 || extractedSteps.length > 0) && (
            <div className="alert alert-success" style={{marginBottom:'1rem'}}>
              Extracted {extractedSteps.length} step{extractedSteps.length === 1 ? '' : 's'} and{' '}
              {extractedIngredients.length} ingredient{extractedIngredients.length === 1 ? '' : 's'}.
              After creating the recipe, you'll be walked through adding each ingredient.
            </div>
          )}

          <div className="divider"></div>

          {/* Create Recipe Button */}
          <button
            className="btn btn-primary"
            onClick={handleCreateRecipe}
            disabled={saving || !recipeName.trim()}
            style={{width:'100%', padding:'0.75rem', fontSize:'0.9rem'}}
          >
            {saving ? 'Creating Recipe...' : 'Create Recipe'}
          </button>
        </div>
      )}

      {/* Search existing recipes */}
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
