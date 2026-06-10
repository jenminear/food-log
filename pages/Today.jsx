import { useEffect, useState } from 'react'
import { getDailyNutrition } from './api.js'
import { NutGrid } from '../components/NutGrid.jsx'

export default function Today() {
  const today = new Date().toISOString().slice(0, 10)
  const [date, setDate]   = useState(today)
  const [data, setData]   = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    setError(null)
    getDailyNutrition(date)
      .then(setData)
      .catch(e => setError(e.message))
  }, [date])

  return (
    <>
      <div className="page-header">
        <span className="page-title">Today</span>
        <input type="date" value={date} onChange={e => setDate(e.target.value)}
               style={{width:'auto'}} />
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {data && (
        <>
          <div className="card mb-2">
            <div className="card-header">
              <h2>Daily Totals</h2>
            </div>
            <NutGrid data={data.daily_totals} />
          </div>

          {data.meals.length === 0
            ? <div className="empty">No meals logged for this day.</div>
            : data.meals.map((meal, i) => (
              <div className="card" key={i}>
                <div className="card-header">
                  <h2 style={{textTransform:'capitalize'}}>{meal.meal_type}</h2>
                  <span className="text-faint text-sm">{meal.meal_date}</span>
                </div>
                <NutGrid data={meal.totals} />
                {meal.components && meal.components.length > 0 && (
                  <div className="table-wrap mt-2">
                    <table>
                      <thead>
                        <tr>
                          <th>Ingredient</th>
                          <th>kcal</th>
                          <th>Protein</th>
                          <th>Fat</th>
                          <th>Carbs</th>
                          <th>Fiber</th>
                        </tr>
                      </thead>
                      <tbody>
                        {meal.components.map((c, j) => (
                          <tr key={j}>
                            <td>{c.ingredient_name}</td>
                            <td className="mono">{c.calories?.toFixed(1)}</td>
                            <td className="mono">{c.protein_grams?.toFixed(1)}</td>
                            <td className="mono">{c.fat_grams?.toFixed(1)}</td>
                            <td className="mono">{c.carb_grams?.toFixed(1)}</td>
                            <td className="mono">{c.fiber_grams?.toFixed(1)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ))
          }
        </>
      )}
    </>
  )
}
