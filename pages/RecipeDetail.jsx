import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import {
  getRecipe, updateRecipe, deleteRecipe, createBatchFromId,
  getRecipeBatches, getBatch, deleteBatch,
  searchIngredientLocal, searchIngredient, resolveIngredient, getIngredient,
  updateIngredient, addRecipeComponent, updateRecipeComponent, deleteRecipeComponent,
  addBatchComponent, updateBatchComponent, deleteBatchComponent,
  getNotes, addNote, updateNote, deleteNote,
  estimateIngredientWeight, imageUrl,
} from './api.js'
import { convertToPortionUnits, isGramUnit, computeCalories, isHighCalorieOutlier } from './unitConversion.js'

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
  portion_grams: '',
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

// Round to ~4 significant digits for display (e.g. 793.7861 -> "793.8",
// 0.020999996 -> "0.021") — auto-converted quantities can otherwise show
// long floating-point tails that needlessly widen the Qty column.
function formatQty(value) {
  if (value == null || isNaN(value)) return ''
  return Number(value.toPrecision(4)).toString()
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
  const [candidateLimit, setCandidateLimit] = useState(5)
  const [loadingMoreCandidates, setLoadingMoreCandidates] = useState(false)
  const [verifyCandidate, setVerifyCandidate] = useState(null)
  const [verifyPortionIdx, setVerifyPortionIdx] = useState(0)
  const [showManualEntry, setShowManualEntry] = useState(false)
  const [manualData, setManualData] = useState(EMPTY_MANUAL)
  const [resolvedIngredient, setResolvedIngredient] = useState(null)
  const [quantity, setQuantity] = useState('')
  const [quantityWarning, setQuantityWarning] = useState(null)
  const [calorieConfirmNeeded, setCalorieConfirmNeeded] = useState(false)
  const [originalQtyText, setOriginalQtyText] = useState('')
  const [notFound, setNotFound] = useState(false)
  const [searching, setSearching] = useState(false)
  const debounceRef = useRef(null)

  // ── Lock / batch-view state ──────────────────────────────────────────────
  // A recipe is locked (frozen, read-only ingredients/steps) the moment it
  // has any batch at all — no separate "complete" flag is stored. Only the
  // single most-recently-created batch for a recipe is ever editable; every
  // earlier batch is a permanent historical record. `viewingBatchId` is
  // null when looking at the original frozen recipe, or a batch_id when
  // looking at (and possibly editing) a specific batch.
  const [batches, setBatches] = useState([])
  const [viewingBatchId, setViewingBatchId] = useState(null)
  const [batchIsEditable, setBatchIsEditable] = useState(false)
  const [deletingRecipe, setDeletingRecipe] = useState(false)
  const [deletingBatch, setDeletingBatch] = useState(false)

  // ── Ingredient detail/edit modal state ──────────────────────────────────
  const [editingComponent, setEditingComponent] = useState(null) // ComponentSummary row
  const [editForm, setEditForm] = useState(null) // editable copy of ingredient + quantity_multiple
  const [savingEdit, setSavingEdit] = useState(false)
  const [editCalorieConfirmNeeded, setEditCalorieConfirmNeeded] = useState(false)

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
    getRecipeBatches(id).then(setBatches).catch(() => setBatches([]))

    // Arrived here from a meal's "click to view the batch" link — jump
    // straight to that batch's view instead of the frozen recipe.
    if (location.state?.viewBatchId != null) {
      loadBatchView(location.state.viewBatchId)
    }
  }, [id])

  // Switch the displayed ingredients/notes back to the original frozen recipe.
  async function loadRecipeView() {
    setError(null)
    try {
      const r = await getRecipe(id)
      setRecipe(r)
      setComponents(r.components || [])
      setSteps(parseSteps(r.steps_txt))
      setViewingBatchId(null)
      setNotes(await getNotes({ recipe_id: id }))
      resetPanel()
    } catch (e) {
      setError('Failed to load recipe: ' + e.message)
    }
  }

  // Re-fetch the canonical component list for the batch currently being
  // edited. Required after every batch-mode add/update/delete: the first
  // mutation to a batch copies ALL of the recipe's components to new
  // batch-level component_ids (copy-on-write) — patching just the one row
  // that was touched leaves every other row's id stale, which then 404s
  // ("Component id=X not found on batch id=Y") the next time any of them
  // is edited, since the resolver only re-derives ids on that first copy.
  async function refreshBatchComponents() {
    const batch = await getBatch(viewingBatchId)
    setComponents(batch.components || [])
  }

  // Switch the displayed ingredients/notes to a specific batch's snapshot.
  async function loadBatchView(batchId) {
    setError(null)
    try {
      const batch = await getBatch(batchId)
      setComponents(batch.components || [])
      setBatchIsEditable(batch.is_editable)
      setViewingBatchId(batchId)
      setNotes(await getNotes({ batch_id: batchId }))
      resetPanel()
    } catch (e) {
      setError('Failed to load batch: ' + e.message)
    }
  }

  // Whether the currently-displayed ingredient list is editable: the
  // original recipe is editable only before its first batch; a batch is
  // editable only while it's the most recent one for its recipe. Steps are
  // recipe-only and lock the same time the recipe does, regardless of
  // which batch is being viewed. Notes are never locked.
  const isEditable    = recipe ? (viewingBatchId == null ? !recipe.is_locked : batchIsEditable) : false
  const stepsEditable = recipe ? !recipe.is_locked : false

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
        const parent = viewingBatchId == null ? { recipe_id: parseInt(id) } : { batch_id: viewingBatchId }
        const result = await addNote({ note_txt: currentNote, ...parent })
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

  // If the local search comes back empty, fall through to the external
  // (USDA / Open Food Facts) search — no extra click required. Debounced
  // on its own (not just piggybacking on the local-search debounce): if
  // the user pauses briefly mid-phrase (e.g. typing "can of tomatoes"),
  // local search can resolve empty for "can" alone, and without this
  // delay the USDA search would fire immediately for that fragment —
  // surfacing results like "canola oil" before the rest of the phrase is
  // even typed. Re-running on every `nameInput` change cancels any
  // pending fallback search the instant the user types more.
  useEffect(() => {
    if (
      localSearchDone && localMatches.length === 0 &&
      !resolvedIngredient && !showManualEntry &&
      !usdaCandidates && !notFound && !searching
    ) {
      const t = setTimeout(() => handleNoneOfThese(), 500)
      return () => clearTimeout(t)
    }
  }, [localSearchDone, localMatches, nameInput])

  // Auto-open the add-ingredient panel for the next pending (AI-extracted)
  // ingredient. Search using its cleaned-up `search_name` (e.g. "tomato")
  // rather than the full recipe text (e.g. "ripe tomato, chopped
  // (optional)") — searching the full descriptive phrase tends to surface
  // irrelevant products (see unitConversion.js / search_name comments).
  useEffect(() => {
    if (pendingIngredients.length > 0 && !panelOpen && !resolvedIngredient) {
      setPanelOpen(true)
      setNameInput(pendingIngredients[0].search_name || pendingIngredients[0].name)
    }
  }, [pendingIngredients, panelOpen, resolvedIngredient])

  // Once an ingredient is resolved during import, pre-fill the quantity
  // from the recipe's extracted amount — converting it into however many
  // of the resolved portion_unit that represents (e.g. "2 tbsp" -> cups).
  // If the table/density conversion can't handle it at all (count-based
  // amounts like "2 avocados", no fixed weight), ask the AI weight
  // estimator as a last resort before giving up and using the raw number
  // as-is. Flags whichever fallback (if any) was used.
  useEffect(() => {
    if (pendingIngredients.length > 0 && resolvedIngredient && !quantity) {
      const pending = pendingIngredients[0]
      if (pending.quantity != null) {
        const converted = pending.unit
          ? convertToPortionUnits(pending.quantity, pending.unit, resolvedIngredient.portion_unit, resolvedIngredient.portion_grams, pending.name)
          : null
        if (converted) {
          setQuantity(String(converted.value))
          if (converted.estimated) {
            setQuantityWarning(
              `Estimated from "${pending.quantity} ${pending.unit}" using an approximate ` +
              `ingredient density — double-check this quantity.`
            )
          }
        } else {
          // Table/density conversion couldn't handle it — try the AI
          // weight estimator before falling back to the raw number as-is.
          estimateIngredientWeight(pending.name, pending.quantity, pending.unit)
            .then(result => {
              if (result.found && resolvedIngredient.portion_grams > 0) {
                setQuantity(String(Math.round((result.grams / resolvedIngredient.portion_grams) * 1000) / 1000))
                setQuantityWarning(
                  `AI-estimated ~${Math.round(result.grams)}g for "${pending.quantity} ${pending.unit}" ` +
                  `(${result.confidence} confidence) — not a real lookup, verify if it matters.`
                )
              } else {
                setQuantity(String(pending.quantity))
                setQuantityWarning(
                  `Couldn't auto-convert "${pending.quantity}${pending.unit ? ' ' + pending.unit : ''}" ` +
                  `to ${resolvedIngredient.portion_unit} — entered as-is, please verify.`
                )
              }
            })
            .catch(() => {
              setQuantity(String(pending.quantity))
              setQuantityWarning(
                `Couldn't auto-convert "${pending.quantity}${pending.unit ? ' ' + pending.unit : ''}" ` +
                `to ${resolvedIngredient.portion_unit} — entered as-is, please verify.`
              )
            })
        }
      }
      setOriginalQtyText(
        pending.original_quantity_text ||
        (pending.quantity != null ? `${pending.quantity}${pending.unit ? ' ' + pending.unit : ''}` : '')
      )
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
    setError(null)
    try {
      // Cooking from a specific past batch mirrors THAT batch's ingredients
      // and notes (including any substitutions made then) — not the
      // original recipe.
      const batch = await createBatchFromId(id, { sourceBatchId: viewingBatchId })
      setRecipe(prev => prev ? { ...prev, is_locked: true } : prev)
      setBatches(prev => [{ batch_id: batch.batch_id, date: batch.batch_date }, ...prev])
      setComponents(batch.components || [])
      setBatchIsEditable(true)
      setViewingBatchId(batch.batch_id)
      setNotes(await getNotes({ batch_id: batch.batch_id }))
      resetPanel()
    } catch(e) { setError(e.message) }
    finally { setCooking(false) }
  }

  async function handleDeleteRecipe() {
    if (!confirm('Delete this recipe? This cannot be undone.')) return
    setDeletingRecipe(true)
    setError(null)
    try {
      await deleteRecipe(id)
      navigate('/recipes')
    } catch (e) {
      setError('Failed to delete recipe: ' + e.message)
      setDeletingRecipe(false)
    }
  }

  async function handleDeleteBatch() {
    if (!confirm('Delete this batch? This cannot be undone.')) return
    setDeletingBatch(true)
    setError(null)
    try {
      await deleteBatch(viewingBatchId)
      const updated = await getRecipeBatches(id)
      setBatches(updated)
      if (updated.length > 0) {
        await loadBatchView(updated[0].batch_id)
      } else {
        await loadRecipeView()
      }
    } catch (e) {
      setError('Failed to delete batch: ' + e.message)
    } finally {
      setDeletingBatch(false)
    }
  }

  // ========== ADD-INGREDIENT PANEL ==========

  function resetPanel() {
    setPanelOpen(false)
    setNameInput('')
    setLocalMatches([])
    setLocalSearchDone(false)
    setUsdaCandidates(null)
    setCandidateLimit(5)
    setLoadingMoreCandidates(false)
    setVerifyCandidate(null)
    setVerifyPortionIdx(0)
    setShowManualEntry(false)
    setManualData(EMPTY_MANUAL)
    setResolvedIngredient(null)
    setQuantity('')
    setQuantityWarning(null)
    setCalorieConfirmNeeded(false)
    setOriginalQtyText('')
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

  // "More options" — re-search with a higher limit to surface candidates
  // beyond the initial top 5 (e.g. when none of them look right).
  async function handleLoadMoreCandidates() {
    if (!nameInput.trim()) return
    setLoadingMoreCandidates(true)
    setError(null)
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
      setError('Failed to save ingredient: ' + e.message)
    }
  }

  function openManualEntry() {
    setUsdaCandidates(null)
    setShowManualEntry(true)
    setManualData(prev => ({ ...prev, ingredient_name: nameInput.trim() }))
  }

  // For things like water, salt, or spices where nutrition is negligible
  // or simply not worth looking up — skips search entirely and adds the
  // ingredient with no nutrition values (left blank, not zeroed, so it's
  // honestly "unknown" rather than asserting 0 — editable later).
  async function handleSkipNutritionLookup() {
    if (!nameInput.trim()) return
    setError(null)
    try {
      const resolved = await resolveIngredient({
        ingredient_name: nameInput.trim(),
        manual_data: {
          portion_unit: 'g',
          portion_grams: 1,
          calories: null,
          protein_grams: null,
          fat_grams: null,
          carb_grams: null,
          fiber_grams: null,
          nutrition_info_source: 'Skipped — no nutrition lookup',
        },
      })
      setResolvedIngredient(resolved)
    } catch (e) {
      setError('Failed to add ingredient: ' + e.message)
    }
  }

  async function submitManualEntry() {
    setError(null)
    try {
      const unit = manualData.portion_unit.trim()
      const portionG = isGramUnit(unit) ? 1 : parseFloat(manualData.portion_grams) || 100
      const toP100 = v => v === '' ? null : (parseFloat(v) / portionG * 100)
      const resolved = await resolveIngredient({
        ingredient_name: manualData.ingredient_name.trim(),
        manual_data: {
          portion_unit: unit,
          portion_grams: portionG,
          calories:      toP100(manualData.calories),
          protein_grams: toP100(manualData.protein_grams),
          fat_grams:     toP100(manualData.fat_grams),
          carb_grams:    toP100(manualData.carb_grams),
          fiber_grams:   toP100(manualData.fiber_grams),
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
    if (!calorieConfirmNeeded && isHighCalorieOutlier(resolvedIngredient.calories, resolvedIngredient.portion_grams, parseFloat(quantity))) {
      setCalorieConfirmNeeded(true)
      return
    }
    setError(null)
    try {
      const payload = {
        ingredient_id: resolvedIngredient.ingredient_id,
        quantity_multiple: parseFloat(quantity),
        original_quantity_text: originalQtyText.trim() || null,
      }
      if (viewingBatchId == null) {
        const component = await addRecipeComponent(id, payload)
        setComponents(prev => [...prev, component])
      } else {
        await addBatchComponent(viewingBatchId, payload)
        await refreshBatchComponents()
      }
      resetPanel()
      advanceImportQueue()
    } catch (e) {
      setError('Failed to add ingredient: ' + e.message)
    }
  }

  async function handleDeleteComponent(componentId) {
    if (!confirm('Remove this ingredient?')) return
    setError(null)
    try {
      if (viewingBatchId == null) {
        await deleteRecipeComponent(id, componentId)
        setComponents(prev => prev.filter(c => c.component_id !== componentId))
      } else {
        await deleteBatchComponent(viewingBatchId, componentId)
        await refreshBatchComponents()
      }
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
        data_quality_warning: detail.data_quality_warning,
        quantity_multiple: component.quantity_multiple,
        original_quantity_text: component.original_quantity_text || '',
      })
    } catch (e) {
      setError('Failed to load ingredient: ' + e.message)
    }
  }

  function closeEditModal() {
    setEditingComponent(null)
    setEditForm(null)
    setEditCalorieConfirmNeeded(false)
  }

  function updateEditField(key, value) {
    setEditForm(prev => ({ ...prev, [key]: value }))
    setEditCalorieConfirmNeeded(false)
  }

  async function saveEdit() {
    if (!editingComponent || !editForm) return
    const newQuantityCheck = parseFloat(editForm.quantity_multiple)
    const newCaloriesCheck = editForm.calories === '' || editForm.calories == null ? null : parseFloat(editForm.calories)
    const newPortionGramsCheck = parseFloat(editForm.portion_grams)
    if (!editCalorieConfirmNeeded && isHighCalorieOutlier(newCaloriesCheck, newPortionGramsCheck, newQuantityCheck)) {
      setEditCalorieConfirmNeeded(true)
      return
    }
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
      const newOriginalText = editForm.original_quantity_text?.trim() || null

      await updateIngredient(editingComponent.ingredient_id, ingredientFields)

      const quantityChanged = newQuantity !== editingComponent.quantity_multiple
      const originalTextChanged = newOriginalText !== (editingComponent.original_quantity_text || null)

      if (viewingBatchId == null) {
        let updatedComponent = { ...editingComponent, ...ingredientFields }
        if (quantityChanged || originalTextChanged) {
          const payload = { quantity_multiple: newQuantity, original_quantity_text: newOriginalText }
          updatedComponent = { ...await updateRecipeComponent(id, editingComponent.component_id, payload), ...ingredientFields }
        }
        setComponents(prev => prev.map(c => c.component_id === editingComponent.component_id ? updatedComponent : c))
      } else {
        if (quantityChanged || originalTextChanged) {
          const payload = { quantity_multiple: newQuantity, original_quantity_text: newOriginalText }
          await updateBatchComponent(viewingBatchId, editingComponent.component_id, payload)
        }
        // Always refresh from the server in batch mode: even when only the
        // shared ingredient fields changed (no quantity/text edit, so no
        // updateBatchComponent call above), the very first batch mutation
        // may have happened on an EARLIER edit and left other rows' ids
        // stale — refreshing keeps every row's component_id authoritative.
        await refreshBatchComponents()
      }
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
        <div style={{display:'flex', gap:'0.5rem', alignItems:'center'}}>
          {!recipe.is_locked && (
            <button className="btn btn-secondary" onClick={handleDeleteRecipe} disabled={deletingRecipe}>
              {deletingRecipe ? 'Deleting…' : 'Delete Recipe'}
            </button>
          )}
          {viewingBatchId != null && batchIsEditable && (
            <button className="btn btn-secondary" onClick={handleDeleteBatch} disabled={deletingBatch}>
              {deletingBatch ? 'Deleting…' : 'Delete Batch'}
            </button>
          )}
          <button className="btn btn-primary" onClick={handleCook} disabled={cooking}>
            {cooking ? 'Starting…' : '🥘 Cook This'}
          </button>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="card">
        <div style={{display:'flex', gap:'1.25rem', alignItems:'flex-start'}}>
          {recipe.picture_path && (
            <img
              src={imageUrl(recipe.picture_path)}
              alt={recipe.recipe_name}
              style={{width:'140px', height:'140px', objectFit:'cover', borderRadius:'6px', flexShrink:0}}
            />
          )}
          <div style={{flex:1}}>
            <div className="btn-group mb-1">
              {recipe.vegan      && <span className="badge badge-green">vegan</span>}
              {recipe.vegetarian && <span className="badge badge-green">vegetarian</span>}
              {recipe.need_oven  && <span className="badge badge-yellow">oven</span>}
              {!recipe.is_locked && <span className="badge">draft — not yet cooked</span>}
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
        </div>
      </div>

      {components.length > 0 && recipe.num_servings > 0 && (() => {
        const nutKeys = ['calories', 'protein_grams', 'fat_grams', 'carb_grams', 'fiber_grams']
        const totals = {}
        for (const k of nutKeys) {
          const vals = components.map(c => c[k] != null ? c[k] * (c.portion_grams / 100) * c.quantity_multiple : null)
          totals[k] = vals.every(v => v == null) ? null : vals.reduce((a, v) => (a ?? 0) + (v ?? 0), null)
        }
        const perServing = k => totals[k] != null ? (totals[k] / recipe.num_servings).toFixed(k === 'calories' ? 0 : 1) : '—'
        return (
          <div className="card">
            <h2 style={{marginBottom:'0.5rem'}}>Nutrition per Serving</h2>
            <p className="text-sm text-faint" style={{marginBottom:'0.75rem'}}>
              {recipe.num_servings} servings · totals from current ingredient list
            </p>
            <div style={{display:'grid', gridTemplateColumns:'repeat(5, 1fr)', gap:'0.5rem', textAlign:'center'}}>
              {[
                {k:'calories',label:'kcal'},
                {k:'protein_grams',label:'Protein'},
                {k:'fat_grams',label:'Fat'},
                {k:'carb_grams',label:'Carbs'},
                {k:'fiber_grams',label:'Fiber'},
              ].map(({k,label}) => (
                <div key={k}>
                  <div className="mono" style={{fontSize:'1.1rem', fontWeight:600}}>{perServing(k)}</div>
                  <div className="text-sm text-faint">{label}</div>
                </div>
              ))}
            </div>
          </div>
        )
      })()}

      {batches.length > 0 && (
        <div className="card">
          <h2 style={{marginBottom:'0.75rem'}}>Batches</h2>
          <p className="text-sm text-faint" style={{marginBottom:'0.75rem'}}>
            Each time you cook this, the ingredients/notes below can diverge from the original
            recipe. Past batches are a permanent record — only the most recent one is editable.
          </p>
          <div style={{display:'flex', gap:'0.5rem', flexWrap:'wrap'}}>
            <button
              className={'btn ' + (viewingBatchId == null ? 'btn-primary' : 'btn-secondary')}
              onClick={loadRecipeView}
            >
              Original Recipe
            </button>
            {batches.map(b => (
              <button
                key={b.batch_id}
                className={'btn ' + (viewingBatchId === b.batch_id ? 'btn-primary' : 'btn-secondary')}
                onClick={() => loadBatchView(b.batch_id)}
              >
                {b.date}{batches[0].batch_id === b.batch_id ? ' (latest)' : ''}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="card">
        <h2 style={{marginBottom:'1rem'}}>
          Ingredients
          {viewingBatchId != null && <span className="text-sm text-faint"> — batch from {batches.find(b => b.batch_id === viewingBatchId)?.date}</span>}
        </h2>

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
                  <th style={{textAlign:'left'}}>Ingredient</th>
                  <th style={{textAlign:'left'}}>Recipe Amount</th>
                  <th>Qty</th>
                  <th>Unit</th>
                  <th>kcal</th>
                  <th>Protein</th>
                  <th>Carbs</th>
                  <th>Fat</th>
                  <th>Fiber</th>
                  {isEditable && <th></th>}
                </tr>
              </thead>
              <tbody>
                {components.map(c => (
                  <tr key={c.component_id}>
                    <td style={{textAlign:'left'}}>
                      {isEditable ? (
                        <button
                          className="link-btn"
                          style={{background:'none', border:'none', padding:0, color:'var(--accent)', cursor:'pointer', textDecoration:'underline', textAlign:'left'}}
                          onClick={() => openEditModal(c)}
                        >
                          {c.ingredient_name}
                        </button>
                      ) : c.ingredient_name}
                    </td>
                    <td className="text-sm text-faint" style={{textAlign:'left'}}>{c.original_quantity_text || '—'}</td>
                    <td className="mono">{formatQty(c.quantity_multiple)}</td>
                    <td className="mono">{c.portion_unit}</td>
                    <td className="mono">{scaled(c.calories, c.portion_grams, c.quantity_multiple)?.toFixed(0)}</td>
                    <td className="mono">{scaled(c.protein_grams, c.portion_grams, c.quantity_multiple)?.toFixed(1)}</td>
                    <td className="mono">{scaled(c.carb_grams, c.portion_grams, c.quantity_multiple)?.toFixed(1)}</td>
                    <td className="mono">{scaled(c.fat_grams, c.portion_grams, c.quantity_multiple)?.toFixed(1)}</td>
                    <td className="mono">{scaled(c.fiber_grams, c.portion_grams, c.quantity_multiple)?.toFixed(1)}</td>
                    {isEditable && (
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
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {components.length === 0 && !panelOpen && (
          <div className="empty">No ingredients yet.</div>
        )}

        {isEditable && <div className="divider"></div>}

        {isEditable && !panelOpen && (
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
                  <div style={{display:'flex', gap:'0.5rem', alignItems:'flex-start'}}>
                    <input
                      type="text"
                      value={nameInput}
                      onChange={e => { setNameInput(e.target.value); setUsdaCandidates(null); setNotFound(false) }}
                      placeholder="e.g. rolled oats"
                      autoFocus
                      style={{flex:1}}
                    />
                    <button
                      type="button" className="btn btn-secondary"
                      onClick={handleSkipNutritionLookup}
                      disabled={!nameInput.trim()}
                      title="For things like water, salt, or spices where nutrition is negligible"
                    >
                      Skip nutrition lookup
                    </button>
                  </div>
                  {localMatches.length > 0 && (
                    <div className="candidate-list">
                      {localMatches.map(m => (
                        <div key={m.ingredient_id} className="candidate-item" onClick={() => pickLocalMatch(m)}>
                          <div style={{flex:1}}>
                            <div className="candidate-name">{m.ingredient_name}</div>
                            <div className="candidate-meta">
                              {m.calories} kcal · {m.portion_unit} ({m.portion_grams}g)
                            </div>
                            {m.data_quality_warning && (
                              <div className="text-sm" style={{color:'var(--warn, #b8860b)'}}>
                                ⚠ {m.data_quality_warning}
                              </div>
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
                              <div className="text-sm" style={{color:'var(--warn, #b8860b)'}}>
                                ⚠ {c.data_quality_warning}
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                    <div style={{marginTop:'0.5rem', display:'flex', gap:'0.5rem'}}>
                      <button className="btn btn-secondary" onClick={handleLoadMoreCandidates} disabled={loadingMoreCandidates}>
                        {loadingMoreCandidates ? 'Loading…' : 'More options'}
                      </button>
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
                            {isGramUnit(p.unit)
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
                <div className="form-row">
                  <div className="form-group">
                    <label>Portion Unit <span style={{color:'red'}}>*</span></label>
                    <input type="text" placeholder='e.g. "1 cup"' value={manualData.portion_unit}
                      onChange={e => setManualData({...manualData, portion_unit: e.target.value})} />
                  </div>
                  <div className="form-group">
                    <label>Portion Weight (g) <span style={{color:'red'}}>*</span></label>
                    <input type="number" min="0.1" step="1" placeholder="e.g. 240"
                      value={manualData.portion_grams}
                      onChange={e => setManualData({...manualData, portion_grams: e.target.value})} />
                  </div>
                </div>
                <p className="text-sm text-faint" style={{marginBottom:'0.5rem'}}>
                  Nutrition values below are per 1 portion{manualData.portion_grams ? ` (${manualData.portion_grams}g)` : ''} (optional):
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
                    disabled={!manualData.ingredient_name || !manualData.portion_unit || !manualData.portion_grams}
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
                      {!quantityWarning && ' — converted to the quantity below, adjust if needed'}
                    </div>
                  )}
                  {resolvedIngredient.data_quality_warning && (
                    <div className="text-sm" style={{color:'var(--warn, #b8860b)', marginTop:'0.25rem'}}>
                      ⚠ {resolvedIngredient.data_quality_warning}
                    </div>
                  )}
                  {quantityWarning && (
                    <div className="text-sm" style={{color:'var(--warn, #b8860b)', marginTop:'0.25rem'}}>
                      ⚠ {quantityWarning}
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
                      type="number"
                      value={quantity}
                      onChange={e => { setQuantity(e.target.value); setCalorieConfirmNeeded(false) }}
                      min="0.01"
                      step="0.1"
                      autoFocus
                      onKeyDown={e => e.key === 'Enter' && handleAddIngredient()}
                    />
                  </div>
                  <div className="form-group" style={{margin:0, maxWidth:'14rem'}}>
                    <label>Recipe wording (optional)</label>
                    <input
                      type="text"
                      value={originalQtyText}
                      onChange={e => setOriginalQtyText(e.target.value)}
                      placeholder={`e.g. "2 tbsp"`}
                      onKeyDown={e => e.key === 'Enter' && handleAddIngredient()}
                    />
                  </div>
                  <button className="btn btn-primary" onClick={handleAddIngredient} disabled={!quantity.trim()}>
                    {calorieConfirmNeeded ? "Yes, that's right" : 'Add Ingredient'}
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
                {stepsEditable && (
                  <>
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
                  </>
                )}
              </div>
            ))}
          </div>
        )}

        {steps.length === 0 && !stepsEditable && (
          <div className="empty">No steps recorded.</div>
        )}

        {stepsEditable && (
          <>
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
          </>
        )}
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

            {editForm.data_quality_warning && (
              <div className="alert alert-warn" style={{marginBottom:'1rem'}}>
                ⚠ {editForm.data_quality_warning}
              </div>
            )}

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
              <div className="form-group">
                <label>Recipe wording (optional)</label>
                <input type="text" placeholder={`e.g. "2 tbsp"`} value={editForm.original_quantity_text}
                  onChange={e => updateEditField('original_quantity_text', e.target.value)} />
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

            {editCalorieConfirmNeeded && (
              <div className="alert alert-warn" style={{marginTop:'1rem'}}>
                ⚠ That's {Math.round(computeCalories(
                  editForm.calories === '' || editForm.calories == null ? null : parseFloat(editForm.calories),
                  parseFloat(editForm.portion_grams) || 0,
                  parseFloat(editForm.quantity_multiple) || 0,
                ))} calories for this quantity — sure that's right?
              </div>
            )}
            <div style={{display:'flex', gap:'0.5rem', justifyContent:'flex-end', marginTop:'1rem'}}>
              <button className="btn btn-secondary" onClick={closeEditModal}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={saveEdit} disabled={savingEdit}>
                {savingEdit ? 'Saving…' : editCalorieConfirmNeeded ? "Yes, that's right" : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
