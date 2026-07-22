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

function mealLabel(type) {
  return type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

// ── Mobile meal card ─────────────────────────────────────────────────────────

function MealCard({ meal, onDelete, onGoToBatch }) {
  const nut = meal.nutrition ?? {}

  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', padding: '1rem', display: 'flex',
      flexDirection: 'column', gap: '0.75rem',
    }}>
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
        <span style={{fontWeight:500, fontSize:'0.875rem', textTransform:'capitalize'}}>
          {mealLabel(meal.meal_type)}
        </span>
        <button className="btn btn-secondary"
          style={{padding:'0.2rem 0.5rem', fontSize:'0.75rem'}}
          onClick={() => onDelete(meal.meal_id)}>
          Delete
        </button>
      </div>

      {meal.source === 'batch' ? (
        <div>
          {meal.recipe_id != null ? (
            <button onClick={() => onGoToBatch(meal)}
              style={{background:'none', border:'none', padding:0, color:'var(--accent)',
                cursor:'pointer', textDecoration:'underline', fontSize:'0.875rem',
                textAlign:'left', fontWeight:500}}>
              {meal.recipe_name}
            </button>
          ) : (
            <span style={{fontSize:'0.875rem', fontWeight:500}}>{meal.recipe_name}</span>
          )}
          <div style={{fontSize:'0.8rem', color:'var(--text-faint)', marginTop:'0.2rem'}}>
            {fmtBatchDate(meal.batch_date)} · {((meal.fraction_of_batch ?? 1) * 100).toFixed(0)}%
          </div>
        </div>
      ) : (
        <div style={{display:'flex', flexDirection:'column', gap:'0.3rem'}}>
          {(meal.components ?? []).map((c, i) => (
            <div key={i} style={{display:'flex', justifyContent:'space-between',
              fontSize:'0.8rem', color:'var(--text-mid)'}}>
              <span>{c.ingredient_name}</span>
              <span style={{color:'var(--text-faint)', fontFamily:'var(--mono)'}}>
                {fmt(c.quantity_multiple)}× {c.portion_unit}
              </span>
            </div>
          ))}
          {(!meal.components || meal.components.length === 0) && (
            <span style={{fontSize:'0.8rem', color:'var(--text-faint)'}}>no ingredients</span>
          )}
        </div>
      )}

      {/* Mini nutrition row */}
      <div style={{display:'grid', gridTemplateColumns:'repeat(5,1fr)', gap:'0.35rem'}}>
        {[
          ['kcal', meal.source === 'batch' ? nut.calories?.toFixed(0) : null],
          ['pro', meal.source === 'batch' ? nut.protein_grams?.toFixed(1) : null],
          ['fat', meal.source === 'batch' ? nut.fat_grams?.toFixed(1) : null],
          ['carb', meal.source === 'batch' ? nut.carb_grams?.toFixed(1) : null],
          ['fiber', meal.source === 'batch' ? nut.fiber_grams?.toFixed(1) : null],
        ].map(([label, val]) => (
          <div key={label} style={{background:'var(--bg)', border:'1px solid var(--border)',
            borderRadius:'var(--radius)', padding:'0.4rem 0.3rem', textAlign:'center'}}>
            <div style={{fontFamily:'var(--mono)', fontSize:'0.8rem', fontWeight:500}}>
              {val ?? '—'}
            </div>
            <div style={{fontSize:'0.6rem', color:'var(--text-faint)', textTransform:'uppercase',
              letterSpacing:'0.05em'}}>
              {label}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Mobile carousel ──────────────────────────────────────────────────────────

function MobileView({ data, sortedMeals, onDelete, onGoToBatch }) {
  const [active, setActive] = useState(0)
  const total = 1 + sortedMeals.length

  function onScroll(e) {
    const i = Math.round(e.target.scrollLeft / e.target.offsetWidth)
    setActive(i)
  }

  return (
    <div>
      {/* Scrollable track */}
      <div onScroll={onScroll} style={{
        display: 'flex', overflowX: 'auto', scrollSnapType: 'x mandatory',
        scrollBehavior: 'smooth', gap: '0.75rem',
        paddingBottom: '0.5rem',
        WebkitOverflowScrolling: 'touch',
        msOverflowStyle: 'none', scrollbarWidth: 'none',
      }}>
        {/* Card 0: Daily Totals */}
        <div style={{minWidth:'100%', scrollSnapAlign:'start'}}>
          <div className="card" style={{marginBottom:0}}>
            <div className="card-header"><h2>Daily Totals</h2></div>
            <NutGrid data={data.daily_totals} />
          </div>
        </div>

        {/* One card per meal */}
        {sortedMeals.map((meal, i) => (
          <div key={meal.meal_id} style={{minWidth:'100%', scrollSnapAlign:'start'}}>
            <MealCard meal={meal} onDelete={onDelete} onGoToBatch={onGoToBatch} />
          </div>
        ))}

        {sortedMeals.length === 0 && (
          <div style={{minWidth:'100%', scrollSnapAlign:'start'}}>
            <div className="empty">No meals logged for this day.</div>
          </div>
        )}
      </div>

      {/* Dot indicators */}
      <div style={{display:'flex', justifyContent:'center', gap:'0.4rem', marginTop:'0.75rem'}}>
        {Array.from({length: total}).map((_, i) => (
          <div key={i} style={{
            width: i === active ? '1.5rem' : '0.45rem',
            height: '0.45rem',
            borderRadius: '1rem',
            background: i === active ? 'var(--accent)' : 'var(--border-mid)',
            transition: 'all 0.2s',
          }} />
        ))}
      </div>
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────────────────

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
          {/* ── Desktop table view ── */}
          <div className="today-desktop">
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
          </div>

          {/* ── Mobile carousel view ── */}
          <div className="today-mobile">
            <MobileView
              data={data}
              sortedMeals={sortedMeals}
              onDelete={handleDeleteMeal}
              onGoToBatch={goToBatch}
            />
          </div>
        </>
      )}
    </>
  )
}
