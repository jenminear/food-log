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

function fmtBatchDate(dateStr) {
  if (!dateStr) return 'batch'
  const [y, m, d] = dateStr.split('-')
  return `batch (${parseInt(m)}/${parseInt(d)}/${y.slice(2)})`
}

export default function Today() {
  const navigate = useNavigate()
  const now = new Date()
  const today = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`
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
                      <th style={{textAlign:'left'}}>Portion</th>
                      <th>Qty</th>
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
                            <td style={{textAlign:'left', textTransform:'capitalize', fontSize:'0.8rem'}}>
                              {meal.meal_type.replace('_', ' ')}
                            </td>
                            <td style={{textAlign:'left', fontSize:'0.8rem'}}>
                              {meal.recipe_id != null ? (
                                <button
                                  className="link-btn"
                                  style={{background:'none', border:'none', padding:0, color:'var(--accent)', cursor:'pointer', textDecoration:'underline', fontSize:'0.8rem', textAlign:'left', display:'block', width:'100%'}}
                                  onClick={() => goToBatch(meal)}
                                >
                                  {meal.recipe_name}
                                </button>
                              ) : (
                                <span style={{fontSize:'0.8rem'}}>{meal.recipe_name}</span>
                              )}
                            </td>
                            <td style={{textAlign:'left', color:'var(--text-faint)', fontSize:'0.8rem'}}>
                              {fmtBatchDate(meal.batch_date)}
                            </td>
                            <td className="mono" style={{color:'var(--text-faint)', fontSize:'0.8rem'}}>{((meal.fraction_of_batch ?? 1) * 100).toFixed(0)}%</td>
                            <td className="mono" style={{fontSize:'0.8rem'}}>{fmt(meal.nutrition.calories, 0)}</td>
                            <td className="mono" style={{fontSize:'0.8rem'}}>{fmt(meal.nutrition.protein_grams)}</td>
                            <td className="mono" style={{fontSize:'0.8rem'}}>{fmt(meal.nutrition.fat_grams)}</td>
                            <td className="mono" style={{fontSize:'0.8rem'}}>{fmt(meal.nutrition.carb_grams)}</td>
                            <td className="mono" style={{fontSize:'0.8rem'}}>{fmt(meal.nutrition.fiber_grams)}</td>
                            <td>
                              <button className="btn btn-secondary" style={{padding:'0.25rem 0.5rem', fontSize:'0.8rem'}}
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
                                <td rowSpan={rows.length} style={{textAlign:'left', textTransform:'capitalize', fontSize:'0.8rem'}}>
                                  {meal.meal_type.replace('_', ' ')}
                                </td>
                              )}
                              <td style={{textAlign:'left', fontSize:'0.8rem'}}>{c ? c.ingredient_name : <span className="text-faint">no ingredients</span>}</td>
                              <td style={{textAlign:'left', color:'var(--text-faint)', fontSize:'0.8rem'}}>{c ? c.portion_unit : ''}</td>
                              <td className="mono" style={{color:'var(--text-faint)', fontSize:'0.8rem'}}>{c ? fmt(c.quantity_multiple) : '—'}</td>
                              <td className="mono" style={{fontSize:'0.8rem'}}>{c ? fmt(c.calories, 0) : '—'}</td>
                              <td className="mono" style={{fontSize:'0.8rem'}}>{c ? fmt(c.protein_grams) : '—'}</td>
                              <td className="mono" style={{fontSize:'0.8rem'}}>{c ? fmt(c.fat_grams) : '—'}</td>
                              <td className="mono" style={{fontSize:'0.8rem'}}>{c ? fmt(c.carb_grams) : '—'}</td>
                              <td className="mono" style={{fontSize:'0.8rem'}}>{c ? fmt(c.fiber_grams) : '—'}</td>
                              {j === 0 && (
                                <td rowSpan={rows.length}>
                                  <button className="btn btn-secondary" style={{padding:'0.25rem 0.5rem', fontSize:'0.8rem'}}
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
