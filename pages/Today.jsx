import { Fragment, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getDailyNutrition, deleteMeal } from './api.js'
import { NutGrid } from '../components/NutGrid.jsx'
import LogMealModal from './Meals.jsx'

const MEAL_TYPE_ORDER = [
  'breakfast', 'morning_snack', 'lunch', 'afternoon_snack', 'dinner', 'evening_snack',
]

function mealTypeRank(mealType) {
  const i = MEAL_TYPE_ORDER.indexOf(mealType)
  return i === -1 ? MEAL_TYPE_ORDER.length : i
}

function fmt(n, digits = 1) {
  return n == null ? '—' : n.toFixed(digits)
}

export default function Today() {
  const navigate = useNavigate()
  const today = new Date().toISOString().slice(0, 10)
  const [date, setDate]   = useState(today)
  const [data, setData]   = useState(null)
  const [error, setError] = useState(null)
  const [showLogMeal, setShowLogMeal] = useState(false)

  function refresh() {
    setError(null)
    getDailyNutrition(date)
      .then(setData)
      .catch(e => setError(e.message))
  }

  useEffect(refresh, [date])

  async function handleDeleteMeal(mealId) {
    if (!confirm('Delete this meal?')) return
    setError(null)
    try {
      await deleteMeal(mealId)
      refresh()
    } catch (e) {
      setError('Failed to delete meal: ' + e.message)
    }
  }

  function goToBatch(meal) {
    if (meal.recipe_id == null) return
    navigate(`/recipes/${meal.recipe_id}`, { state: { viewBatchId: meal.batch_id } })
  }

  const sortedMeals = data
    ? [...data.meals].sort((a, b) => mealTypeRank(a.meal_type) - mealTypeRank(b.meal_type) || a.timestamp - b.timestamp)
    : []

  return (
    <>
      <div className="page-header">
        <span className="page-title">Today</span>
        <div style={{display:'flex', gap:'0.5rem'}}>
          <input type="date" value={date} onChange={e => setDate(e.target.value)}
                 style={{width:'auto'}} />
          <button className="btn btn-primary" onClick={() => setShowLogMeal(true)}>
            + Add Meal
          </button>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {showLogMeal && (
        <LogMealModal
          date={date}
          onClose={() => setShowLogMeal(false)}
          onLogged={refresh}
        />
      )}

      {data && (
        <>
          <div className="card mb-2">
            <div className="card-header">
              <h2>Daily Totals</h2>
            </div>
            <NutGrid data={data.daily_totals} />
          </div>

          {sortedMeals.length === 0 ? (
            <div className="empty">No meals logged for this day.</div>
          ) : (
            <div className="card">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th style={{textAlign:'left'}}>Meal</th>
                      <th style={{textAlign:'left'}}>Details</th>
                      <th>kcal</th>
                      <th>Protein</th>
                      <th>Fat</th>
                      <th>Carbs</th>
                      <th>Fiber</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedMeals.map(meal => {
                      if (meal.source === 'batch') {
                        return (
                          <tr key={meal.meal_id}>
                            <td style={{textAlign:'left', textTransform:'capitalize'}}>
                              {meal.meal_type.replace('_', ' ')}
                            </td>
                            <td style={{textAlign:'left'}}>
                              {meal.recipe_id != null ? (
                                <button
                                  className="link-btn"
                                  style={{background:'none', border:'none', padding:0, color:'var(--accent)', cursor:'pointer', textDecoration:'underline'}}
                                  onClick={() => goToBatch(meal)}
                                >
                                  {meal.recipe_name} — {((meal.fraction_of_batch ?? 1) * 100).toFixed(0)}% of batch
                                </button>
                              ) : (
                                <span>{meal.recipe_name} — {((meal.fraction_of_batch ?? 1) * 100).toFixed(0)}% of batch</span>
                              )}
                            </td>
                            <td className="mono">{fmt(meal.nutrition.calories, 0)}</td>
                            <td className="mono">{fmt(meal.nutrition.protein_grams)}</td>
                            <td className="mono">{fmt(meal.nutrition.fat_grams)}</td>
                            <td className="mono">{fmt(meal.nutrition.carb_grams)}</td>
                            <td className="mono">{fmt(meal.nutrition.fiber_grams)}</td>
                            <td>
                              <button className="btn btn-secondary" style={{padding:'0.25rem 0.5rem', fontSize:'0.875rem'}}
                                onClick={() => handleDeleteMeal(meal.meal_id)}>
                                Delete
                              </button>
                            </td>
                          </tr>
                        )
                      }

                      // Standalone meal: one row per ingredient, no
                      // meal-level totals row. Meal type and Delete span
                      // all of that meal's rows so they're shown once.
                      const rows = meal.components?.length > 0 ? meal.components : [null]
                      return (
                        <Fragment key={meal.meal_id}>
                          {rows.map((c, j) => (
                            <tr key={j}>
                              {j === 0 && (
                                <td rowSpan={rows.length} style={{textAlign:'left', textTransform:'capitalize'}}>
                                  {meal.meal_type.replace('_', ' ')}
                                </td>
                              )}
                              <td style={{textAlign:'left'}}>{c ? c.ingredient_name : <span className="text-faint">no ingredients</span>}</td>
                              <td className="mono">{c ? fmt(c.calories, 0) : '—'}</td>
                              <td className="mono">{c ? fmt(c.protein_grams) : '—'}</td>
                              <td className="mono">{c ? fmt(c.fat_grams) : '—'}</td>
                              <td className="mono">{c ? fmt(c.carb_grams) : '—'}</td>
                              <td className="mono">{c ? fmt(c.fiber_grams) : '—'}</td>
                              {j === 0 && (
                                <td rowSpan={rows.length}>
                                  <button className="btn btn-secondary" style={{padding:'0.25rem 0.5rem', fontSize:'0.875rem'}}
                                    onClick={() => handleDeleteMeal(meal.meal_id)}>
                                    Delete
                                  </button>
                                </td>
                              )}
                            </tr>
                          ))}
                        </Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </>
  )
}
