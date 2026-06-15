import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import {
  getRecipe, updateRecipe, createBatchFromId,
  searchIngredientLocal, searchIngredient, resolveIngredient, getIngredient,
  updateIngredient, addRecipeComponent, updateRecipeComponent, deleteRecipeComponent,
  getNotes, addNote, updateNote, deleteNote,
} from './api.js'
import { convertToPortionUnits } from './unitConversion.js'

const NUTRITION_FIELDS = [
  { key: 'calories',      label: 'Calories', step: '1'   },
  { key: 'protein_grams', label: 'Protein (g)', step: '0.1' },
  { key: 'fat_grams',     label: 'Fat (g)',     step: '0.1' },
  { key: 'carb_grams',    label: 'Carbs (g)',   step: '0.1' },
  { key: 'fiber_grams',   label: 'Fiber (g)',   step: '0.1' },
]

const EMPTY_MANUAL = {
  ingredient_name: '',
  portion_unit: '',
  calories: '',
  protein_grams: '',
  fat_grams: '',
  carb_grams: '',
  fiber_grams: '',
}

function scaled(value, portionGrams, quantityMultiple) {
  if (value == null) return null
  return value * (portionGrams / 100) * quantityMultiple
}

export default function RecipeDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const [recipe, setRecipe] = useState(null)
  const [components, setComponents] = useState([])
  const [error,  setError]  = useState(null)
  const [cooking, setCooking] = useState(false)

  // ── Add-ingredient panel state ──────────────────────────────────────────
  const [panelOpen, setPanelOpen] = useState(false)
  const [nameInput, setNameInput] = useState('')
  const [localMatches, setLocalMatches] = useState([])
  const [localSearchDone, setLocalSearchDone] = useState(false)
  const [usdaCandidates, setUsdaCandidates] = useState(null)
  const [verifyCandidate, setVerifyCandidate] = useState(null)
  const [verifyPortionIdx, setVerifyPortionIdx] = useState(0)
  const [showManualEntry, setShowManualEntry] = useState(false)
  const [manualData, setManualData] = useState(EMPTY_MANUAL)
  const [resolvedIngredient, setResolvedIngredient] = useState(null)
  const [quantity, setQuantity] = useState('')
  const [notFound, setNotFound] = useState(false)
  const [searching, setSearching] = useState(false)
  const debounceRef = useRef(null)

  // ── Ingredient detail/edit modal state ──────────────────────────────────
  const [editingComponent, setEditingComponent] = useState(null) // ComponentSummary row
  const [editForm, setEditForm] = useState(null) // editable copy of ingredient + quantity_multiple
  const [savingEdit, setSavingEdit] = useState(false)

  // ── Steps state ──────────────────────────────────────────────────────────
  const [steps, setSteps] = useState([])
  const [currentStep, setCurrentStep] = useState('')
  const [editingStepIndex, setEditingStepIndex] = useState(null)

  // ── Notes state ──────────────────────────────────────────────────────────
  const [notes, setNotes] = useState([])
  const [currentNote, setCurrentNote] = useState('')
  const [editingNoteId, setEditingNoteId] = useState(null)

  // ── Guided ingredient import (from AI recipe extraction) ────────────────
  const [pendingIngredients, setPendingIngredients] = useState(() =>
    (location.state?.pendingIngredients || []).filter(i => i?.name?.trim())
  )
  const [importComplete, setImportComplete] = useState(false)

  useEffect(() => {
    getRecipe(id).then(r => {
      setRecipe(r)
      setComponents(r.components || [])
      setSteps(parseSteps(r.steps_txt))
    }).catch(e => setError(e.message))

    getNotes({ recipe_id: id }).then(setNotes).catch(() => setNotes([]))
  }, [id])

  function parseSteps(stepsTxt) {
    if (!stepsTxt) return []
    try {
      const parsed = JSON.parse(stepsTxt)
      return Array.isArray(parsed) ? parsed : [stepsTxt]
    } catch {
      return [stepsTxt]
    }
  }

  async function persistSteps(newSteps) {
    await updateRecipe(id, {
      recipe_name:      recipe.recipe_name,
      steps_txt:        newSteps.length > 0 ? JSON.stringify(newSteps) : null,
      num_servings:     recipe.num_servings,
      active_time_mins: recipe.active_time_mins,
      total_time_mins:  recipe.total_time_mins,
      need_oven:        recipe.need_oven,
      vegan:            recipe.vegan,
      vegetarian:       recipe.vegetarian,
      source:           recipe.source,
    })
    setSteps(newSteps)
    setRecipe(prev => ({ ...prev, steps_txt: newSteps.length > 0 ? JSON.stringify(newSteps) : null }))
  }

  async function handleAddStep() {
    if (!currentStep.trim()) return
    setError(null)
    try {
      const newSteps = [...steps]
      if (editingStepIndex !== null) {
        newSteps[editingStepIndex] = currentStep
      } else {
        newSteps.push(currentStep)
      }
      await persistSteps(newSteps)
      setCurrentStep('')
      setEditingStepIndex(null)
    } catch (e) {
      setError('Failed to save step: ' + e.message)
    }
  }

  function handleEditStep(index) {
    setCurrentStep(steps[index])
    setEditingStepIndex(index)
  }

  async function handleDeleteStep(index) {
    setError(null)
    try {
      const newSteps = steps.filter((_, i) => i !== index)
      await persistSteps(newSteps)
      if (editingStepIndex === index) {
        setEditingStepIndex(null)
        setCurrentStep('')
      }
    } catch (e) {
      setError('Failed to delete step: ' + e.message)
    }
  }

  // ── Notes handlers ───────────────────────────────────────────────────────

  async function handleAddNote() {
    if (!currentNote.trim()) return
    setError(null)
    try {
      if (editingNoteId !== null) {
        const updated = await updateNote(editingNoteId, { note_txt: currentNote })
        setNotes(prev => prev.map(n => n.note_id === editingNoteId ? updated : n))
        setEditingNoteId(null)
      } else {
        const result = await addNote({ note_txt: currentNote, recipe_id: parseInt(id) })
        setNotes(prev => [{ note_id: result.note_id, note_date: result.note_date, note_txt: currentNote }, ...prev])
      }
      setCurrentNote('')
    } catch (e) {
      setError('Failed to save note: ' + e.message)
    }
  }

  function handleEditNote(note) {
    setCurrentNote(note.note_txt)
    setEditingNoteId(note.note_id)
  }

  async function handleDeleteNote(noteId) {
    if (!confirm('Delete this note?')) return
    setError(null)
    try {
      await deleteNote(noteId)
      setNotes(prev => prev.filter(n => n.note_id !== noteId))
      if (editingNoteId === noteId) {
        setEditingNoteId(null)
        setCurrentNote('')
      }
    } catch (e) {
      setError('Failed to delete note: ' + e.message)
    }
  }

  // Debounced local search as the user types an ingredient name
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (resolvedIngredient || nameInput.trim().length < 2) {
      setLocalMatches([])
      setLocalSearchDone(false)
      return
    }
    setLocalSearchDone(false)
    debounceRef.current = setTimeout(() => {
      searchIngredientLocal(nameInput.trim())
        .then(matches => { setLocalMatches(matches); setLocalSearchDone(true) })
        .catch(() => { setLocalMatches([]); setLocalSearchDone(true) })
    }, 300)
    return () => clearTimeout(debounceRef.current)
  }, [nameInput, resolvedIngredient])

  // If the local search comes back empty, fall straight through to the
  // external (USDA / Open Food Facts) search — no extra click required.
  useEffect(() => {
    if (
      localSearchDone && localMatches.length === 0 &&
      !resolvedIngredient && !showManualEntry &&
      !usdaCandidates && !notFound && !searching
    ) {
      handleNoneOfThese()
    }
  }, [localSearchDone, localMatches])

  // Auto-open the add-ingredient panel for the next pending (AI-extracted)
  // ingredient, pre-filling its name so the normal search flow runs.
  useEffect(() => {
    if (pendingIngredients.length > 0 && !panelOpen && !resolvedIngredient) {
      setPanelOpen(true)
      setNameInput(pendingIngredients[0].name)
    }
  }, [pendingIngredients, panelOpen, resolvedIngredient])

  // Once an ingredient is resolved during import, pre-fill the quantity
  // from the recipe's extracted amount — converting it into however many
  // of the resolved portion_unit that represents (e.g. "2 tbsp" -> cups),
  // falling back to the raw extracted number if units aren't convertible.
  useEffect(() => {
    if (pendingIngredients.length > 0 && resolvedIngredient && !quantity) {
      const pending = pendingIngredients[0]
      if (pending.quantity != null) {
        const converted = pending.unit
          ? convertToPortionUnits(pending.quantity, pending.unit, resolvedIngredient.portion_unit)
          : null
        setQuantity(String(converted ?? pending.quantity))
      }
    }
  }, [resolvedIngredient])

  function advanceImportQueue() {
    setPendingIngredients(prev => {
      const next = prev.slice(1)
      if (prev.length > 0 && next.length === 0) setImportComplete(true)
      return next
    })
  }

  function handleSkipIngredient() {
    resetPanel()
    advanceImportQueue()
  }

  function handleSkipAllIngredients() {
    resetPanel()
    setPendingIngredients([])
  }

  async function handleCook() {
    setCooking(true)
    try {
      const batch = await createBatchFromId(id)
      navigate(`/batches/${batch.batch_id}`)
    } catch(e) { setError(e.message) }
    finally { setCooking(false) }
  }

  // ========== ADD-INGREDIENT PANEL ==========

  function resetPanel() {
    setPanelOpen(false)
    setNameInput('')
    setLocalMatches([])
    setLocalSearchDone(false)
    setUsdaCandidates(null)
    setVerifyCandidate(null)
    setVerifyPortionIdx(0)
    setShowManualEntry(false)
    setManualData(EMPTY_MANUAL)
    setResolvedIngredient(null)
    setQuantity('')
    setNotFound(false)
    setSearching(false)
  }

  // Build the list of selectable portion options for a USDA/OFF candidate:
  // its own portion_unit/portion_grams plus any alternatives from all_portions,
  // de-duplicated.
  function getPortionOptions(candidate) {
    const opts = []
    const seen = new Set()
    const add = (unit, grams) => {
      const key = `${unit}|${grams}`
      if (!seen.has(key)) { seen.add(key); opts.push({ unit, grams }) }
    }
    add(candidate.portion_unit, candidate.portion_grams)
    for (const p of candidate.all_portions || []) add(p.unit, p.grams)
    return opts
  }

  function pickLocalMatch(match) {
    setResolvedIngredient(match)
    setLocalMatches([])
  }

  async function handleNoneOfThese() {
    if (!nameInput.trim()) return
    setSearching(true)
    setError(null)
    setLocalMatches([])
    try {
      const result = await searchIngredient(nameInput.trim(), true)
      if (result.status === 'found') {
        if (result.ingredient.ingredient_id != null) {
          setResolvedIngredient(result.ingredient)
        } else {
          setUsdaCandidates([result.ingredient])
          setVerifyCandidate(result.ingredient)
          setVerifyPortionIdx(0)
        }
      } else if (result.status === 'candidates') {
        setUsdaCandidates(result.candidates)
      } else {
        setNotFound(true)
        setShowManualEntry(true)
        setManualData(prev => ({ ...prev, ingredient_name: nameInput.trim() }))
      }
    } catch (e) {
      setError('Ingredient search failed: ' + e.message)
    } finally {
      setSearching(false)
    }
  }

  function openVerifyCandidate(candidate) {
    setVerifyCandidate(candidate)
    setVerifyPortionIdx(0)
  }

  async function confirmVerifiedCandidate() {
    if (!verifyCandidate) return
    setError(null)
    try {
      const opts = getPortionOptions(verifyCandidate)
      const chosen = opts[verifyPortionIdx] || opts[0]
      const isGramUnit = ['g', 'gram', 'grams'].includes(chosen.unit.trim().toLowerCase())
      const candidate = { ...verifyCandidate, portion_unit: chosen.unit, portion_grams: isGramUnit ? 1 : chosen.grams }
      const resolved = await resolveIngredient({
        ingredient_name: nameInput.trim(),
        candidate,
      })
      setResolvedIngredient(resolved)
      setUsdaCandidates(null)
      setVerifyCandidate(null)
    } catch (e) {
      setError('Failed to save ingredient: ' + e.message)
    }
  }

  function openManualEntry() {
    setUsdaCandidates(null)
    setShowManualEntry(true)
    setManualData(prev => ({ ...prev, ingredient_name: nameInput.trim() }))
  }

  async function submitManualEntry() {
    setError(null)
    try {
      const unit = manualData.portion_unit.trim()
      const isGramUnit = ['g', 'gram', 'grams'].includes(unit.toLowerCase())
      const resolved = await resolveIngredient({
        ingredient_name: manualData.ingredient_name.trim(),
        manual_data: {
          portion_unit: unit,
          portion_grams: isGramUnit ? 1 : 100,
          calories: manualData.calories === '' ? null : parseFloat(manualData.calories),
          protein_grams: manualData.protein_grams === '' ? null : parseFloat(manualData.protein_grams),
          fat_grams: manualData.fat_grams === '' ? null : parseFloat(manualData.fat_grams),
          carb_grams: manualData.carb_grams === '' ? null : parseFloat(manualData.carb_grams),
          fiber_grams: manualData.fiber_grams === '' ? null : parseFloat(manualData.fiber_grams),
        },
      })
      setResolvedIngredient(resolved)
      setShowManualEntry(false)
      setNotFound(false)
    } catch (e) {
      setError('Failed to save ingredient: ' + e.message)
    }
  }

  async function handleAddIngredient() {
    if (!resolvedIngredient || !quantity.trim()) return
    setError(null)
    try {
      const component = await addRecipeComponent(id, {
        ingredient_id: resolvedIngredient.ingredient_id,
        quantity_multiple: parseFloat(quantity),
      })
      setComponents(prev => [...prev, component])
      resetPanel()
      advanceImportQueue()
    } catch (e) {
      setError('Failed to add ingredient: ' + e.message)
    }
  }

  async function handleDeleteComponent(componentId) {
    if (!confirm('Remove this ingredient from the recipe?')) return
    setError(null)
    try {
      await deleteRecipeComponent(id, componentId)
      setComponents(prev => prev.filter(c => c.component_id !== componentId))
    } catch (e) {
      setError('Failed to remove ingredient: ' + e.message)
    }
  }

  // ========== INGREDIENT DETAIL / EDIT MODAL ==========

  async function openEditModal(component) {
    setError(null)
    try {
      const detail = await getIngredient(component.ingredient_id)
      setEditingComponent(component)
      setEditForm({
        ingredient_name: detail.ingredient_name,
        portion_unit: detail.portion_unit,
        portion_grams: detail.portion_grams,
        calories: detail.calories,
        protein_grams: detail.protein_grams,
        fat_grams: detail.fat_grams,
        carb_grams: detail.carb_grams,
        fiber_grams: detail.fiber_grams,
        nutrition_info_source: detail.nutrition_info_source,
        quantity_multiple: component.quantity_multiple,
      })
    } catch (e) {
      setError('Failed to load ingredient: ' + e.message)
    }
  }

  function closeEditModal() {
    setEditingComponent(null)
    setEditForm(null)
  }

  function updateEditField(key, value) {
    setEditForm(prev => ({ ...prev, [key]: value }))
  }

  async function saveEdit() {
    if (!editingComponent || !editForm) return
    setSavingEdit(true)
    setError(null)
    try {
      const ingredientFields = {
        ingredient_name: editForm.ingredient_name,
        portion_unit: editForm.portion_unit,
        portion_grams: parseFloat(editForm.portion_grams),
        calories: editForm.calories === '' || editForm.calories == null ? null : parseFloat(editForm.calories),
        protein_grams: editForm.protein_grams === '' || editForm.protein_grams == null ? null : parseFloat(editForm.protein_grams),
        fat_grams: editForm.fat_grams === '' || editForm.fat_grams == null ? null : parseFloat(editForm.fat_grams),
        carb_grams: editForm.carb_grams === '' || editForm.carb_grams == null ? null : parseFloat(editForm.carb_grams),
        fiber_grams: editForm.fiber_grams === '' || editForm.fiber_grams == null ? null : parseFloat(editForm.fiber_grams),
      }
      const newQuantity = parseFloat(editForm.quantity_multiple)

      await updateIngredient(editingComponent.ingredient_id, ingredientFields)

      let updatedComponent = { ...editingComponent, ...ingredientFields, quantity_multiple: editingComponent.quantity_multiple }
      if (newQuantity !== editingComponent.quantity_multiple) {
        updatedComponent = await updateRecipeComponent(id, editingComponent.component_id, { quantity_multiple: newQuantity })
        updatedComponent = { ...updatedComponent, ...ingredientFields }
      }

      setComponents(prev => prev.map(c => c.component_id === editingComponent.component_id ? updatedComponent : c))
      closeEditModal()
    } catch (e) {
      setError('Failed to save changes: ' + e.message)
    } finally {
      setSavingEdit(false)
    }
  }

  if (error)  return <div className="alert alert-error">{error}</div>
  if (!recipe) return <div className="loading-center"><span className="spinner"/></div>

  return (
    <>
      <div className="page-header">
        <span className="page-title">{recipe.recipe_name}</span>
        <button className="btn btn-primary" onClick={handleCook} disabled={cooking}>
          🥘 Cook This
        </button>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="card">
        <div className="btn-group mb-1">
          {recipe.vegan      && <span className="badge badge-green">vegan</span>}
          {recipe.vegetarian && <span className="badge badge-green">vegetarian</span>}
          {recipe.need_oven  && <span className="badge badge-yellow">oven</span>}
        </div>
        <div className="form-row mt-1">
          {recipe.num_servings     && <p>Servings: <strong>{recipe.num_servings}</strong></p>}
          {recipe.active_time_mins && <p>Active: <strong>{recipe.active_time_mins} min</strong></p>}
          {recipe.total_time_mins  && <p>Total: <strong>{recipe.total_time_mins} min</strong></p>}
        </div>
        {recipe.source && (
          <p className="mt-1 text-sm">
            Source: <a href={recipe.source} target="_blank" rel="noreferrer">{recipe.source}</a>
          </p>
        )}
      </div>

      <div className="card">
        <h2 style={{marginBottom:'1rem'}}>Ingredients</h2>

        {pendingIngredients.length > 0 && (
          <div className="alert alert-warn" style={{marginBottom:'1rem'}}>
            <div style={{marginBottom:'0.5rem'}}>
              Importing ingredients from recipe — {pendingIngredients.length} remaining.
              {pendingIngredients[0] && (
                <div className="text-sm">
                  Next: {pendingIngredients[0].name}
                  {pendingIngredients[0].quantity != null
                    ? ` (${pendingIngredients[0].quantity}${pendingIngredients[0].unit ? ' ' + pendingIngredients[0].unit : ''})`
                    : ''}
                </div>
              )}
            </div>
            <div style={{display:'flex', gap:'0.5rem'}}>
              <button className="btn btn-secondary" onClick={handleSkipIngredient}>Skip</button>
              <button className="btn btn-secondary" onClick={handleSkipAllIngredients}>Skip remaining</button>
            </div>
          </div>
        )}

        {importComplete && (
          <div className="alert alert-success" style={{marginBottom:'1rem'}}>
            Finished importing ingredients from the recipe.
            <button className="btn btn-secondary" style={{marginLeft:'0.5rem'}} onClick={() => setImportComplete(false)}>
              Dismiss
            </button>
          </div>
        )}

        {components.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ingredient</th>
                  <th>Qty</th>
                  <th>Unit</th>
                  <th>kcal</th>
                  <th>Protein</th>
                  <th>Carbs</th>
                  <th>Fat</th>
                  <th>Fiber</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {components.map(c => (
                  <tr key={c.component_id}>
                    <td>
                      <button
                        className="link-btn"
                        style={{background:'none', border:'none', padding:0, color:'var(--accent)', cursor:'pointer', textDecoration:'underline'}}
                        onClick={() => openEditModal(c)}
                      >
                        {c.ingredient_name}
                      </button>
                    </td>
                    <td className="mono">{c.quantity_multiple}</td>
                    <td className="mono">{c.portion_unit}</td>
                    <td className="mono">{scaled(c.calories, c.portion_grams, c.quantity_multiple)?.toFixed(0)}</td>
                    <td className="mono">{scaled(c.protein_grams, c.portion_grams, c.quantity_multiple)?.toFixed(1)}</td>
                    <td className="mono">{scaled(c.carb_grams, c.portion_grams, c.quantity_multiple)?.toFixed(1)}</td>
                    <td className="mono">{scaled(c.fat_grams, c.portion_grams, c.quantity_multiple)?.toFixed(1)}</td>
                    <td className="mono">{scaled(c.fiber_grams, c.portion_grams, c.quantity_multiple)?.toFixed(1)}</td>
                    <td>
                      <div style={{display:'flex', gap:'0.25rem'}}>
                        <button
                          className="btn btn-secondary"
                          style={{padding:'0.25rem 0.5rem', fontSize:'0.875rem'}}
                          onClick={() => openEditModal(c)}
                        >
                          Edit
                        </button>
                        <button
                          className="btn btn-secondary"
                          style={{padding:'0.25rem 0.5rem', fontSize:'0.875rem'}}
                          onClick={() => handleDeleteComponent(c.component_id)}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {components.length === 0 && !panelOpen && (
          <div className="empty">No ingredients yet.</div>
        )}

        <div className="divider"></div>

        {!panelOpen && (
          <button className="btn btn-secondary" onClick={() => setPanelOpen(true)}>
            + Add Ingredient
          </button>
        )}

        {panelOpen && (
          <div>
            {/* Step 1/2/3: name input + live local search */}
            {!resolvedIngredient && !showManualEntry && (
              <div>
                <div className="form-group" style={{position:'relative'}}>
                  <label>Ingredient Name</label>
                  <input
                    type="text"
                    value={nameInput}
                    onChange={e => { setNameInput(e.target.value); setUsdaCandidates(null); setNotFound(false) }}
                    placeholder="e.g. rolled oats"
                    autoFocus
                  />
                  {localMatches.length > 0 && (
                    <div className="candidate-list">
                      {localMatches.map(m => (
                        <div key={m.ingredient_id} className="candidate-item" onClick={() => pickLocalMatch(m)}>
                          <div style={{flex:1}}>
                            <div className="candidate-name">{m.ingredient_name}</div>
                            <div className="candidate-meta">
                              {m.calories} kcal · {m.portion_unit} ({m.portion_grams}g)
                            </div>
                          </div>
                        </div>
                      ))}
                      <div className="candidate-item" onClick={handleNoneOfThese}>
                        <div style={{flex:1}}>
                          <div className="candidate-name">None of these — search USDA / Open Food Facts</div>
                        </div>
                      </div>
                    </div>
                  )}
                  {searching && (
                    <div className="text-sm text-faint" style={{marginTop:'0.25rem'}}>
                      Searching USDA / Open Food Facts…
                    </div>
                  )}
                </div>

                {usdaCandidates && !verifyCandidate && (
                  <div className="alert alert-warn" style={{marginBottom:'1rem'}}>
                    <div style={{marginBottom:'0.5rem', fontWeight:500}}>
                      Select a match for "{nameInput}":
                    </div>
                    <div className="candidate-list">
                      {usdaCandidates.map((c, i) => (
                        <div key={i} className="candidate-item" onClick={() => openVerifyCandidate(c)}>
                          <span className="candidate-num">{i+1}</span>
                          <div style={{flex:1}}>
                            <div className="candidate-name">{c.ingredient_name}</div>
                            <div className="candidate-meta">
                              {c.calories} kcal · {c.portion_unit} ({c.portion_grams}g)
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                    <div style={{marginTop:'0.5rem', display:'flex', gap:'0.5rem'}}>
                      <button className="btn btn-secondary" onClick={openManualEntry}>
                        Enter Manually
                      </button>
                      <button className="btn btn-secondary" onClick={resetPanel}>
                        Cancel
                      </button>
                    </div>
                  </div>
                )}

                {verifyCandidate && (
                  <div className="alert alert-warn" style={{marginBottom:'1rem'}}>
                    <div style={{marginBottom:'0.5rem', fontWeight:500}}>
                      Verify "{verifyCandidate.ingredient_name}":
                    </div>
                    <div className="candidate-meta" style={{marginBottom:'0.75rem'}}>
                      Per 100g: {verifyCandidate.calories ?? '?'} kcal · {verifyCandidate.protein_grams ?? '?'}g protein
                      {' · '}{verifyCandidate.fat_grams ?? '?'}g fat · {verifyCandidate.carb_grams ?? '?'}g carbs · {verifyCandidate.fiber_grams ?? '?'}g fiber
                    </div>
                    <div className="form-group">
                      <label>Portion Unit</label>
                      <select value={verifyPortionIdx} onChange={e => setVerifyPortionIdx(Number(e.target.value))}>
                        {getPortionOptions(verifyCandidate).map((p, i) => (
                          <option key={i} value={i}>
                            {['g', 'gram', 'grams'].includes(p.unit.trim().toLowerCase())
                              ? p.unit
                              : `${p.unit} (${p.grams}g)`}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div style={{display:'flex', gap:'0.5rem'}}>
                      <button className="btn btn-primary" onClick={confirmVerifiedCandidate}>
                        Confirm
                      </button>
                      <button className="btn btn-secondary" onClick={() => setVerifyCandidate(null)}>
                        Back
                      </button>
                      <button className="btn btn-secondary" onClick={resetPanel}>
                        Cancel
                      </button>
                    </div>
                  </div>
                )}

                {notFound && !showManualEntry && (
                  <div className="alert alert-warn">
                    No matches found. <button className="btn btn-secondary" onClick={openManualEntry}>Enter Manually</button>
                  </div>
                )}

                {!usdaCandidates && (
                  <div style={{display:'flex', gap:'0.5rem'}}>
                    <button className="btn btn-secondary" onClick={resetPanel}>
                      Cancel
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Manual entry */}
            {showManualEntry && (
              <div>
                <div className="form-group">
                  <label>Ingredient Name <span style={{color:'red'}}>*</span></label>
                  <input
                    type="text"
                    value={manualData.ingredient_name}
                    onChange={e => setManualData({...manualData, ingredient_name: e.target.value})}
                  />
                </div>
                <div className="form-group">
                  <label>Portion Unit <span style={{color:'red'}}>*</span></label>
                  <input type="text" placeholder='e.g. "1 cup"' value={manualData.portion_unit}
                    onChange={e => setManualData({...manualData, portion_unit: e.target.value})} />
                </div>
                <p className="text-sm text-faint" style={{marginBottom:'0.5rem'}}>
                  Nutrition values below are per 100g (optional):
                </p>
                <div className="form-row-3">
                  {NUTRITION_FIELDS.map(f => (
                    <div className="form-group" key={f.key}>
                      <label>{f.label}</label>
                      <input type="number" step={f.step} value={manualData[f.key]}
                        onChange={e => setManualData({...manualData, [f.key]: e.target.value})} />
                    </div>
                  ))}
                </div>
                <div style={{display:'flex', gap:'0.5rem'}}>
                  <button
                    className="btn btn-primary"
                    onClick={submitManualEntry}
                    disabled={!manualData.ingredient_name || !manualData.portion_unit}
                  >
                    Continue
                  </button>
                  <button className="btn btn-secondary" onClick={resetPanel}>
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Step 5: quantity for this recipe */}
            {resolvedIngredient && (
              <div>
                <div className="alert alert-success" style={{marginBottom:'1rem'}}>
                  <strong>{resolvedIngredient.ingredient_name}</strong>
                  <div className="text-sm">Unit: {resolvedIngredient.portion_unit}</div>
                  {pendingIngredients.length > 0 && pendingIngredients[0]?.quantity != null && (
                    <div className="text-sm text-faint">
                      Recipe says: {pendingIngredients[0].quantity}{pendingIngredients[0].unit ? ' ' + pendingIngredients[0].unit : ''}
                      {pendingIngredients[0].unit && convertToPortionUnits(
                        pendingIngredients[0].quantity, pendingIngredients[0].unit, resolvedIngredient.portion_unit
                      ) != null && ' — converted to the quantity below, adjust if needed'}
                    </div>
                  )}
                </div>
                <div className="form-row" style={{alignItems:'flex-end', gap:'0.5rem'}}>
                  <div className="form-group" style={{margin:0, maxWidth:'10rem'}}>
                    <label>Quantity ({resolvedIngredient.portion_unit})</label>
                    <input
                      type="number"
                      value={quantity}
                      onChange={e => setQuantity(e.target.value)}
                      min="0.01"
                      step="0.1"
                      autoFocus
                      onKeyDown={e => e.key === 'Enter' && handleAddIngredient()}
                    />
                  </div>
                  <button className="btn btn-primary" onClick={handleAddIngredient} disabled={!quantity.trim()}>
                    Add Ingredient
                  </button>
                  <button className="btn btn-secondary" onClick={resetPanel}>
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="card">
        <h2 style={{marginBottom:'0.75rem'}}>Steps</h2>

        {steps.length > 0 && (
          <div style={{marginBottom:'1rem'}}>
            {steps.map((step, index) => (
              <div key={index} style={{
                padding:'0.5rem',
                marginBottom:'0.5rem',
                backgroundColor:'#f5f5f5',
                borderRadius:'4px',
                display:'flex',
                gap:'0.5rem'
              }}>
                <strong>{index + 1}.</strong>
                <span style={{flex:1, whiteSpace:'pre-line'}}>{step}</span>
                <button
                  className="btn btn-secondary"
                  style={{padding:'0.25rem 0.5rem', fontSize:'0.875rem'}}
                  onClick={() => handleEditStep(index)}
                >
                  Edit
                </button>
                <button
                  className="btn btn-secondary"
                  style={{padding:'0.25rem 0.5rem', fontSize:'0.875rem'}}
                  onClick={() => handleDeleteStep(index)}
                >
                  Delete
                </button>
              </div>
            ))}
          </div>
        )}

        <textarea
          value={currentStep}
          onChange={e => setCurrentStep(e.target.value)}
          placeholder="Enter step instructions..."
          rows="3"
          style={{marginBottom:'0.5rem'}}
        />
        <div style={{display:'flex', gap:'0.5rem'}}>
          <button
            className="btn btn-secondary"
            onClick={handleAddStep}
            disabled={!currentStep.trim()}
          >
            {editingStepIndex !== null ? 'Update Step' : 'Add Step'}
          </button>
          {editingStepIndex !== null && (
            <button className="btn btn-secondary" onClick={() => { setEditingStepIndex(null); setCurrentStep('') }}>
              Cancel
            </button>
          )}
        </div>
      </div>

      <div className="card">
        <h2 style={{marginBottom:'0.75rem'}}>Notes</h2>

        {notes.length > 0 && (
          <div style={{marginBottom:'1rem'}}>
            {notes.map(note => (
              <div key={note.note_id} style={{
                padding:'0.5rem',
                marginBottom:'0.5rem',
                backgroundColor:'#f5f5f5',
                borderRadius:'4px',
                display:'flex',
                gap:'0.5rem'
              }}>
                <div style={{flex:1}}>
                  <div className="text-sm text-faint">{note.note_date}</div>
                  <span style={{whiteSpace:'pre-line'}}>{note.note_txt}</span>
                </div>
                <button
                  className="btn btn-secondary"
                  style={{padding:'0.25rem 0.5rem', fontSize:'0.875rem'}}
                  onClick={() => handleEditNote(note)}
                >
                  Edit
                </button>
                <button
                  className="btn btn-secondary"
                  style={{padding:'0.25rem 0.5rem', fontSize:'0.875rem'}}
                  onClick={() => handleDeleteNote(note.note_id)}
                >
                  Delete
                </button>
              </div>
            ))}
          </div>
        )}

        <textarea
          value={currentNote}
          onChange={e => setCurrentNote(e.target.value)}
          placeholder="Enter a note..."
          rows="2"
          style={{marginBottom:'0.5rem'}}
        />
        <div style={{display:'flex', gap:'0.5rem'}}>
          <button
            className="btn btn-secondary"
            onClick={handleAddNote}
            disabled={!currentNote.trim()}
          >
            {editingNoteId !== null ? 'Update Note' : 'Add Note'}
          </button>
          {editingNoteId !== null && (
            <button className="btn btn-secondary" onClick={() => { setEditingNoteId(null); setCurrentNote('') }}>
              Cancel
            </button>
          )}
        </div>
      </div>

      {/* Combined ingredient detail/edit modal */}
      {editingComponent && editForm && (
        <div className="modal-overlay" onClick={closeEditModal}>
          <div className="modal-content" onClick={e => e.stopPropagation()} style={{maxWidth:'650px'}}>
            <h3>Edit Ingredient</h3>

            <div className="form-group">
              <label>Ingredient Name</label>
              <input type="text" value={editForm.ingredient_name}
                onChange={e => updateEditField('ingredient_name', e.target.value)} />
            </div>

            <div className="form-row">
              <div className="form-group">
                <label>Portion Unit</label>
                <input type="text" value={editForm.portion_unit}
                  onChange={e => updateEditField('portion_unit', e.target.value)} />
              </div>
              <div className="form-group">
                <label>Portion Grams</label>
                <input type="number" step="0.1" value={editForm.portion_grams}
                  onChange={e => updateEditField('portion_grams', e.target.value)} />
              </div>
            </div>

            <p className="text-sm text-faint" style={{marginBottom:'0.5rem'}}>Per 100g:</p>
            <div className="form-row-3">
              {NUTRITION_FIELDS.map(f => (
                <div className="form-group" key={f.key}>
                  <label>{f.label}</label>
                  <input type="number" step={f.step} value={editForm[f.key] ?? ''}
                    onChange={e => updateEditField(f.key, e.target.value)} />
                </div>
              ))}
            </div>

            <div className="form-group">
              <label>Nutrition Info Source</label>
              <input type="text" value={editForm.nutrition_info_source ?? ''}
                onChange={e => updateEditField('nutrition_info_source', e.target.value)} />
            </div>

            <div className="divider"></div>

            <h4 style={{marginBottom:'0.75rem'}}>In This Recipe</h4>
            <div className="form-row">
              <div className="form-group">
                <label>Quantity ({editForm.portion_unit})</label>
                <input type="number" step="0.1" value={editForm.quantity_multiple}
                  onChange={e => updateEditField('quantity_multiple', e.target.value)} />
              </div>
            </div>

            <p className="text-sm text-faint" style={{marginBottom:'0.5rem'}}>
              Scaled nutrition for this recipe:
            </p>
            <div className="form-row-3">
              {NUTRITION_FIELDS.map(f => {
                const val = scaled(
                  parseFloat(editForm[f.key]),
                  parseFloat(editForm.portion_grams) || 0,
                  parseFloat(editForm.quantity_multiple) || 0,
                )
                return (
                  <div key={f.key}>
                    <div className="text-sm text-faint">{f.label}</div>
                    <div className="mono">{val == null || isNaN(val) ? '—' : val.toFixed(1)}</div>
                  </div>
                )
              })}
            </div>

            <div style={{display:'flex', gap:'0.5rem', justifyContent:'flex-end', marginTop:'1rem'}}>
              <button className="btn btn-secondary" onClick={closeEditModal}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={saveEdit} disabled={savingEdit}>
                {savingEdit ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
