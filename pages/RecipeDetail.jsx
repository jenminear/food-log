import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getRecipe, createBatchFromId } from './api.js'

export default function RecipeDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [recipe, setRecipe] = useState(null)
  const [error,  setError]  = useState(null)
  const [cooking, setCooking] = useState(false)

  useEffect(() => {
    getRecipe(id).then(setRecipe).catch(e => setError(e.message))
  }, [id])

  async function handleCook() {
    setCooking(true)
    try {
      const batch = await createBatchFromId(id)
      navigate(`/batches/${batch.batch_id}`)
    } catch(e) { setError(e.message) }
    finally { setCooking(false) }
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

      {recipe.ingredients?.length > 0 && (
        <div className="card">
          <h2 style={{marginBottom:'1rem'}}>Ingredients</h2>
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
                </tr>
              </thead>
              <tbody>
                {recipe.ingredients.map((ing, i) => (
                  <tr key={i}>
                    <td>{ing.ingredient_name}</td>
                    <td className="mono">{ing.quantity_multiple}</td>
                    <td className="mono">{ing.portion_unit}</td>
                    <td className="mono">{ing.calories?.toFixed(0)}</td>
                    <td className="mono">{ing.protein_grams?.toFixed(1)}</td>
                    <td className="mono">{ing.carb_grams?.toFixed(1)}</td>
                    <td className="mono">{ing.fat_grams?.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {recipe.steps_txt && (
        <div className="card">
          <h2 style={{marginBottom:'0.75rem'}}>Steps</h2>
          <p style={{whiteSpace:'pre-line'}}>{recipe.steps_txt}</p>
        </div>
      )}
    </>
  )
}
