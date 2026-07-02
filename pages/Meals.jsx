import { useEffect, useRef, useState } from 'react'
import {
  searchRecipes, searchIngredientLocal, searchIngredient, resolveIngredient,
  createMeal, addMealComponent,
} from './api.js'
import { isGramUnit, computeCalories, isHighCalorieOutlier } from './unitConversion.js'

const MEAL_TYPES = [
  { value: 'breakfast',       label: 'Breakfast' },
  { value: 'lunch',           label: 'Lunch' },
  { value: 'dinner',          label: 'Dinner' },
  { value: 'morning_snack',   label: 'Morning Snack' },
  { value: 'afternoon_snack', label: 'Afternoon Snack' },
  { value: 'evening_snack',   label: 'Evening Snack' },
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

// A modal for logging a meal — opened from the "Add Meal" button on the
// Today page. `date` is the day currently being viewed there; there's no
// separate date field since the meal is always logged for that day.
export default function LogMealModal({ date, onClose, onLogged }) {
  const [mealType, setMealType] = useState('lunch')

  // A meal is either one selected recipe (batch) OR a list of standalone
  // ingredients — picking one clears the other.
  const [selectedRecipe, setSelectedRecipe] = useState(null)
  const [fractionOfBatch, setFractionOfBatch] = useState('1')
  const [pendingIngredients, setPendingIngredients] = useState([])

  // ── Search / resolve panel — same pattern as RecipeDetail's
  // add-ingredient flow: live local search (recipes + ingredients) ->
  // USDA/OFF fallback -> portion verification / manual entry -> quantity.
  const [nameInput, setNameInput] = useState('')
  const [localRecipes, setLocalRecipes] = useState([])
  const [localIngredients, setLocalIngredients] = useState([])
  const [localSearchDone, setLocalSearchDone] = useState(false)
  const [usdaCandidates, setUsdaCandidates] = useState(null)
  const [candidateLimit, setCandidateLimit] = useState(5)
  const [loadingMoreCandidates, setLoadingMoreCandidates] = useState(false)
  const [verifyCandidate, setVerifyCandidate] = useState(null)
  const [verifyPortionIdx, setVerifyPortionIdx] = useState(0)
  const [showManualEntry, setShowManualEntry] = useState(false)
  const [manualData, setManualData] = useState(EMPTY_MANUAL)
  const [resolvedIngredient, setResolvedIngredient] = useState(null)
  const [quantity, setQuantity] = useState('')
  const [calorieConfirmNeeded, setCalorieConfirmNeeded] = useState(false)
  const [notFound, setNotFound] = useState(false)
  const [searching, setSearching] = useState(false)
  const debounceRef = useRef(null)

  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [loggedMeal, setLoggedMeal] = useState(null)

  // Debounced combined local search (recipes + ingredients) as the user types
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (resolvedIngredient || selectedRecipe || nameInput.trim().length < 2) {
      setLocalRecipes([]); setLocalIngredients([]); setLocalSearchDone(false)
      return
    }
    setLocalSearchDone(false)
    debounceRef.current = setTimeout(() => {
      Promise.all([
        searchRecipes(nameInput.trim()).catch(() => []),
        searchIngredientLocal(nameInput.trim()).catch(() => []),
      ]).then(([recipes, ingredients]) => {
        setLocalRecipes(recipes || [])
        setLocalIngredients(ingredients || [])
        setLocalSearchDone(true)
      })
    }, 300)
    return () => clearTimeout(debounceRef.current)
  }, [nameInput, resolvedIngredient, selectedRecipe])

  // If neither recipes nor ingredients match locally, fall through to
  // USDA/OFF automatically — no extra click required (same as RecipeDetail).
  // Debounced on its own so a brief mid-phrase pause (e.g. typing "can of
  // tomatoes") doesn't fire a USDA search for just "can" before the rest
  // of the phrase is typed — see RecipeDetail.jsx for the full rationale.
  useEffect(() => {
    if (
      localSearchDone && localRecipes.length === 0 && localIngredients.length === 0 &&
      !resolvedIngredient && !showManualEntry && !usdaCandidates && !notFound && !searching
    ) {
      const t = setTimeout(() => handleNoneOfThese(), 500)
      return () => clearTimeout(t)
    }
  }, [localSearchDone, localRecipes, localIngredients, nameInput])

  function resetSearchPanel() {
    setNameInput('')
    setLocalRecipes([]); setLocalIngredients([]); setLocalSearchDone(false)
    setUsdaCandidates(null); setCandidateLimit(5); setLoadingMoreCandidates(false)
    setVerifyCandidate(null); setVerifyPortionIdx(0)
    setShowManualEntry(false); setManualData(EMPTY_MANUAL)
    setResolvedIngredient(null); setQuantity('')
    setCalorieConfirmNeeded(false)
    setNotFound(false); setSearching(false)
  }

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

  function pickRecipe(recipe) {
    setSelectedRecipe(recipe)
    resetSearchPanel()
  }

  function pickLocalIngredient(match) {
    setResolvedIngredient(match)
    setLocalRecipes([]); setLocalIngredients([])
  }

  async function handleNoneOfThese() {
    if (!nameInput.trim()) return
    setSearching(true); setError(null)
    setLocalRecipes([]); setLocalIngredients([])
    setCandidateLimit(5)
    try {
      const result = await searchIngredient(nameInput.trim(), true, 5)
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

  async function handleLoadMoreCandidates() {
    if (!nameInput.trim()) return
    setLoadingMoreCandidates(true); setError(null)
    try {
      const newLimit = candidateLimit + 10
      const result = await searchIngredient(nameInput.trim(), true, newLimit)
      if (result.status === 'candidates') {
        setUsdaCandidates(result.candidates)
        setCandidateLimit(newLimit)
      }
    } catch (e) {
      setError('Failed to load more options: ' + e.message)
    } finally {
      setLoadingMoreCandidates(false)
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
      const candidate = { ...verifyCandidate, portion_unit: chosen.unit, portion_grams: isGramUnit(chosen.unit) ? 1 : chosen.grams }
      const resolved = await resolveIngredient({
        ingredient_name: nameInput.trim(),
        candidate,
      })
      setResolvedIngredient(resolved)
      setUsdaCandidates(null)
      setVerifyCandidate(null)
    } catch (e) {
      setError('Failed to resolve ingredient: ' + e.message)
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
      const resolved = await resolveIngredient({
        ingredient_name: manualData.ingredient_name.trim(),
        manual_data: {
          portion_unit: unit,
          portion_grams: isGramUnit(unit) ? 1 : 100,
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
      setError('Failed to resolve ingredient: ' + e.message)
    }
  }

  // Adds the currently-resolved ingredient to the local pending list (not
  // yet persisted — the meal itself isn't created until "Log Meal").
  function handleAddToMeal() {
    if (!resolvedIngredient || !quantity.trim()) return
    if (!calorieConfirmNeeded && isHighCalorieOutlier(resolvedIngredient.calories, resolvedIngredient.portion_grams, parseFloat(quantity))) {
      setCalorieConfirmNeeded(true)
      return
    }
    setPendingIngredients(prev => [
      ...prev,
      { ...resolvedIngredient, quantity_multiple: parseFloat(quantity), _key: Date.now() },
    ])
    resetSearchPanel()
  }

  function removePendingIngredient(key) {
    setPendingIngredients(prev => prev.filter(p => p._key !== key))
  }

  function clearRecipe() {
    setSelectedRecipe(null)
  }

  async function handleLogMeal() {
    if (!selectedRecipe && pendingIngredients.length === 0) return
    setSaving(true); setError(null)
    try {
      if (selectedRecipe) {
        const meal = await createMeal({
          meal_type: mealType,
          meal_date: date,
          recipe_id: selectedRecipe.recipe_id,
          fraction_of_batch: fractionOfBatch.trim() || '1',
        })
        onLogged?.(meal)
        onClose?.()
      } else {
        const meal = await createMeal({ meal_type: mealType, meal_date: date })
        await Promise.all(pendingIngredients.map(p => addMealComponent(meal.meal_id, {
          ingredient_id: p.ingredient_id,
          quantity_multiple: p.quantity_multiple,
        })))
        onLogged?.(meal)
        onClose?.()
      }
    } catch (e) {
      setError('Failed to log meal: ' + e.message)
    } finally {
      setSaving(false)
    }
  }

  const canLog = (selectedRecipe || pendingIngredients.length > 0) && !saving

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()} style={{maxWidth:'650px'}}>
        <h3>Log a Meal</h3>

        {error && <div className="alert alert-error">{error}</div>}

        <div className="form-row">
          <div className="form-group">
            <label>Meal Type</label>
            <select value={mealType} onChange={e => setMealType(e.target.value)}>
              {MEAL_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
        </div>

        {/* Selected recipe (mutually exclusive with ingredient list) */}
        {selectedRecipe && (
          <div className="alert alert-success" style={{marginBottom:'1rem'}}>
            <div style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
              <div>
                <strong>{selectedRecipe.recipe_name}</strong>
                <div className="text-sm text-faint">Logged from its most recent batch</div>
              </div>
              <button className="btn btn-secondary" onClick={clearRecipe}>Change</button>
            </div>
            <div className="form-group" style={{marginTop:'0.75rem', maxWidth:'12rem'}}>
              <label>Fraction of batch eaten</label>
              <input type="text" placeholder="e.g. 0.5 or 1/3"
                value={fractionOfBatch} onChange={e => setFractionOfBatch(e.target.value)} />
            </div>
          </div>
        )}

        {/* Pending standalone ingredients */}
        {!selectedRecipe && pendingIngredients.length > 0 && (
          <div className="table-wrap" style={{marginBottom:'1rem'}}>
            <table>
              <thead>
                <tr>
                  <th style={{textAlign:'left'}}>Ingredient</th>
                  <th>Qty</th>
                  <th>Unit</th>
                  <th>kcal</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {pendingIngredients.map(p => (
                  <tr key={p._key}>
                    <td style={{textAlign:'left'}}>{p.ingredient_name}</td>
                    <td className="mono">{p.quantity_multiple}</td>
                    <td className="mono">{p.portion_unit}</td>
                    <td className="mono">{scaled(p.calories, p.portion_grams, p.quantity_multiple)?.toFixed(0)}</td>
                    <td>
                      <button className="btn btn-secondary" style={{padding:'0.25rem 0.5rem', fontSize:'0.875rem'}}
                        onClick={() => removePendingIngredient(p._key)}>✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Search panel — only while no recipe is selected */}
        {!selectedRecipe && (
          <div>
            {!resolvedIngredient && !showManualEntry && (
              <div>
                <div className="form-group" style={{position:'relative'}}>
                  <label>What did you eat?</label>
                  <input
                    type="text"
                    value={nameInput}
                    onChange={e => { setNameInput(e.target.value); setUsdaCandidates(null); setNotFound(false) }}
                    placeholder="Search a recipe or ingredient…"
                    autoFocus
                  />
                  {(localRecipes.length > 0 || localIngredients.length > 0) && (
                    <div className="candidate-list">
                      {localRecipes.map(r => (
                        <div key={`r${r.recipe_id}`} className="candidate-item" onClick={() => pickRecipe(r)}>
                          <div style={{flex:1}}>
                            <div className="candidate-name">{r.recipe_name} <span className="badge">recipe</span></div>
                            <div className="candidate-meta">{r.num_servings} servings</div>
                          </div>
                        </div>
                      ))}
                      {localIngredients.map(m => (
                        <div key={`i${m.ingredient_id}`} className="candidate-item" onClick={() => pickLocalIngredient(m)}>
                          <div style={{flex:1}}>
                            <div className="candidate-name">{m.ingredient_name}</div>
                            <div className="candidate-meta">
                              {m.calories} kcal · {m.portion_unit} ({m.portion_grams}g)
                            </div>
                            {m.data_quality_warning && (
                              <div className="text-sm" style={{color:'var(--warn, #b8860b)'}}>⚠ {m.data_quality_warning}</div>
                            )}
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
                            {c.data_quality_warning && (
                              <div className="text-sm" style={{color:'var(--warn, #b8860b)'}}>⚠ {c.data_quality_warning}</div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                    <div style={{marginTop:'0.5rem', display:'flex', gap:'0.5rem'}}>
                      <button className="btn btn-secondary" onClick={handleLoadMoreCandidates} disabled={loadingMoreCandidates}>
                        {loadingMoreCandidates ? 'Loading…' : 'More options'}
                      </button>
                      <button className="btn btn-secondary" onClick={openManualEntry}>Enter Manually</button>
                      <button className="btn btn-secondary" onClick={resetSearchPanel}>Cancel</button>
                    </div>
                  </div>
                )}

                {verifyCandidate && (
                  <div className="alert alert-warn" style={{marginBottom:'1rem'}}>
                    <div style={{marginBottom:'0.5rem', fontWeight:500}}>
                      Verify "{verifyCandidate.ingredient_name}":
                    </div>
                    {verifyCandidate.data_quality_warning && (
                      <div className="text-sm" style={{color:'var(--warn, #b8860b)', marginBottom:'0.5rem'}}>
                        ⚠ {verifyCandidate.data_quality_warning}
                      </div>
                    )}
                    <div className="candidate-meta" style={{marginBottom:'0.75rem'}}>
                      Per 100g: {verifyCandidate.calories ?? '?'} kcal · {verifyCandidate.protein_grams ?? '?'}g protein
                      {' · '}{verifyCandidate.fat_grams ?? '?'}g fat · {verifyCandidate.carb_grams ?? '?'}g carbs · {verifyCandidate.fiber_grams ?? '?'}g fiber
                    </div>
                    <div className="form-group">
                      <label>Portion Unit</label>
                      <select value={verifyPortionIdx} onChange={e => setVerifyPortionIdx(Number(e.target.value))}>
                        {getPortionOptions(verifyCandidate).map((p, i) => (
                          <option key={i} value={i}>
                            {isGramUnit(p.unit) ? p.unit : `${p.unit} (${p.grams}g)`}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div style={{display:'flex', gap:'0.5rem'}}>
                      <button className="btn btn-primary" onClick={confirmVerifiedCandidate}>Confirm</button>
                      <button className="btn btn-secondary" onClick={() => setVerifyCandidate(null)}>Back</button>
                      <button className="btn btn-secondary" onClick={resetSearchPanel}>Cancel</button>
                    </div>
                  </div>
                )}

                {notFound && !showManualEntry && (
                  <div className="alert alert-warn">
                    No matches found. <button className="btn btn-secondary" onClick={openManualEntry}>Enter Manually</button>
                  </div>
                )}
              </div>
            )}

            {/* Manual entry */}
            {showManualEntry && (
              <div>
                <div className="form-group">
                  <label>Ingredient Name <span style={{color:'red'}}>*</span></label>
                  <input type="text" value={manualData.ingredient_name}
                    onChange={e => setManualData({...manualData, ingredient_name: e.target.value})} />
                </div>
                <div className="form-group">
                  <label>Portion Unit <span style={{color:'red'}}>*</span></label>
                  <input type="text" placeholder='e.g. "1 cup"' value={manualData.portion_unit}
                    onChange={e => setManualData({...manualData, portion_unit: e.target.value})} />
                </div>
                <p className="text-sm text-faint" style={{marginBottom:'0.5rem'}}>Nutrition values below are per 100g (optional):</p>
                <div className="form-row-3">
                  {['calories','protein_grams','fat_grams','carb_grams','fiber_grams'].map(key => (
                    <div className="form-group" key={key}>
                      <label>{key.replace('_grams','').replace(/^./, c => c.toUpperCase())}</label>
                      <input type="number" step="0.1" value={manualData[key]}
                        onChange={e => setManualData({...manualData, [key]: e.target.value})} />
                    </div>
                  ))}
                </div>
                <div style={{display:'flex', gap:'0.5rem'}}>
                  <button className="btn btn-primary" onClick={submitManualEntry}
                    disabled={!manualData.ingredient_name.trim() || !manualData.portion_unit.trim()}>
                    Save Ingredient
                  </button>
                  <button className="btn btn-secondary" onClick={resetSearchPanel}>Cancel</button>
                </div>
              </div>
            )}

            {/* Quantity step */}
            {resolvedIngredient && (
              <div>
                <div className="alert alert-success" style={{marginBottom:'1rem'}}>
                  <strong>{resolvedIngredient.ingredient_name}</strong>
                  <div className="text-sm">Unit: {resolvedIngredient.portion_unit}</div>
                  {resolvedIngredient.data_quality_warning && (
                    <div className="text-sm" style={{color:'var(--warn, #b8860b)', marginTop:'0.25rem'}}>
                      ⚠ {resolvedIngredient.data_quality_warning}
                    </div>
                  )}
                </div>
                {calorieConfirmNeeded && (
                  <div className="alert alert-warn" style={{marginBottom:'1rem'}}>
                    ⚠ That's {Math.round(computeCalories(resolvedIngredient.calories, resolvedIngredient.portion_grams, parseFloat(quantity) || 0))} calories for this quantity — sure that's right?
                  </div>
                )}
                <div className="form-row" style={{alignItems:'flex-end', gap:'0.5rem'}}>
                  <div className="form-group" style={{margin:0, maxWidth:'10rem'}}>
                    <label>Quantity ({resolvedIngredient.portion_unit})</label>
                    <input
                      type="number" value={quantity} onChange={e => { setQuantity(e.target.value); setCalorieConfirmNeeded(false) }}
                      min="0.01" step="0.1" autoFocus
                      onKeyDown={e => e.key === 'Enter' && handleAddToMeal()}
                    />
                  </div>
                  <button className="btn btn-primary" onClick={handleAddToMeal} disabled={!quantity.trim()}>
                    {calorieConfirmNeeded ? "Yes, that's right" : 'Add to Meal'}
                  </button>
                  <button className="btn btn-secondary" onClick={resetSearchPanel}>Cancel</button>
                </div>
              </div>
            )}
          </div>
        )}

        <div className="divider"></div>
        <div style={{display:'flex', gap:'0.5rem'}}>
          <button className="btn btn-primary" onClick={handleLogMeal} disabled={!canLog}
            style={{flex:1, padding:'0.75rem', fontSize:'0.9rem'}}>
            {saving ? 'Logging…' : 'Log Meal'}
          </button>
          <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  )
}
