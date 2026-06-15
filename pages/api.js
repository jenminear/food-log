/**
 * api.js — Food Log API client
 * All communication with the FastAPI backend goes through these functions.
 * The base URL is /api which Vite proxies to http://localhost:8000 in dev.
 */

const BASE = '/api'

// Read optional API key from localStorage (set via Settings page later)
const apiKey = () => localStorage.getItem('food_log_api_key') || ''

async function request(method, path, body, isFormData = false) {
  const headers = {}
  if (apiKey()) headers['X-Api-Key'] = apiKey()
  if (body && !isFormData) headers['Content-Type'] = 'application/json'

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body
      ? isFormData ? body : JSON.stringify(body)
      : undefined,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }

  // 204 No Content
  if (res.status === 204) return null
  return res.json()
}

const get    = (path)        => request('GET',    path)
const post   = (path, body)  => request('POST',   path, body)
const put    = (path, body)  => request('PUT',    path, body)
const patch  = (path, body)  => request('PATCH',  path, body)
const del    = (path)        => request('DELETE', path)
const upload = (path, form)  => request('POST',   path, form, true)

// ── Health ────────────────────────────────────────────────────────────────
export const health = () => get('/health')

// ── Recipes ───────────────────────────────────────────────────────────────
export const searchRecipes       = q                => get(`/recipes/search?q=${encodeURIComponent(q)}`)
export const searchIngredient    = (q, externalOnly = false) => get(`/recipes/ingredients/search?q=${encodeURIComponent(q)}${externalOnly ? '&external_only=true' : ''}`)
export const searchIngredientLocal = q              => get(`/recipes/ingredients/local-search?q=${encodeURIComponent(q)}`)
export const resolveIngredient    = body            => post('/recipes/ingredients/resolve', body)
export const getIngredient        = id              => get(`/recipes/ingredients/${id}`)
export const updateIngredient     = (id, body)      => patch(`/recipes/ingredients/${id}`, body)
export const addRecipeComponent   = (id, body)      => post(`/recipes/${id}/components`, body)
export const updateRecipeComponent = (id, cid, body) => patch(`/recipes/${id}/components/${cid}`, body)
export const deleteRecipeComponent = (id, cid)      => del(`/recipes/${id}/components/${cid}`)
export const getRecipe           = id               => get(`/recipes/${id}`)
export const createRecipe        = body             => post('/recipes', body)
export const updateRecipe        = (id, body)       => put(`/recipes/${id}`, body)
export const addRecipeIngredient = (key, body)      => post(`/recipes/${key}/ingredients`, body)
export const confirmRecipeIngredient = (key, body)  => post(`/recipes/${key}/ingredients/confirm`, body)
export const addRecipeNote       = (key, body)      => post(`/recipes/${key}/notes`, body)
export const finishRecipe        = key              => post(`/recipes/${key}/finish`)
export const uploadRecipeImage   = (id, file)       => {
  const form = new FormData()
  form.append('file', file)
  return upload(`/recipes/${id}/image`, form)
}
export const extractRecipeFromUrl   = url          => post('/recipes/extract/url', { url })
export const extractRecipeFromImage = file         => {
  const form = new FormData()
  form.append('file', file)
  return upload('/recipes/extract/image', form)
}

// ── Batches ───────────────────────────────────────────────────────────────
export const createBatch          = q               => post(`/batches?recipe_query=${encodeURIComponent(q)}`)
export const createBatchFromId    = (id, date)      => post(`/batches/from-recipe/${id}${date ? `?batch_date=${date}` : ''}`)
export const getBatch             = id              => get(`/batches/${id}`)
export const modifyBatch          = (id, body)      => patch(`/batches/${id}`, body)
export const confirmBatchIngredient = (id, body)    => post(`/batches/${id}/ingredients/confirm`, body)
export const addBatchNote         = (id, note)      => post(`/batches/${id}/notes?note_txt=${encodeURIComponent(note)}`)
export const uploadBatchImage     = (id, file)      => {
  const form = new FormData()
  form.append('file', file)
  return upload(`/batches/${id}/image`, form)
}

// ── Meals ─────────────────────────────────────────────────────────────────
export const startMeal            = body            => post('/meals/start', body)
export const selectRecipeForMeal  = body            => post('/meals/select-recipe', body)
export const startStandalone      = key             => post(`/meals/start-standalone?session_key=${key}`)
export const addMealIngredient    = (key, body)     => post(`/meals/${key}/ingredients`, body)
export const confirmMealIngredient = (key, body)    => post(`/meals/${key}/ingredients/confirm`, body)
export const addMealNote          = (key, note)     => post(`/meals/${key}/notes?note_txt=${encodeURIComponent(note)}`)
export const finishMeal           = key             => post(`/meals/${key}/finish`)
export const getMeal              = id              => get(`/meals/${id}`)

// ── Nutrition ─────────────────────────────────────────────────────────────
export const getDailyNutrition    = date            => get(`/nutrition/daily${date ? `?date=${date}` : ''}`)
export const getRangeNutrition    = (start, end)    => get(`/nutrition/range?start_date=${start}&end_date=${end}`)

// ── Notes ─────────────────────────────────────────────────────────────────
export const addNote              = body            => post('/notes', body)
export const getNotes             = params          => get(`/notes?${new URLSearchParams(params)}`)
export const updateNote           = (id, body)      => patch(`/notes/${id}`, body)
export const deleteNote           = id              => del(`/notes/${id}`)
