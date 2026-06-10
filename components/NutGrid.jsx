export function NutGrid({ data }) {
  if (!data) return null
  const fields = [
    { key: 'calories',      label: 'kcal' },
    { key: 'protein_grams', label: 'protein' },
    { key: 'fat_grams',     label: 'fat' },
    { key: 'carb_grams',    label: 'carbs' },
    { key: 'fiber_grams',   label: 'fiber' },
  ]
  return (
    <div className="nut-grid">
      {fields.map(f => (
        <div className="nut-cell" key={f.key}>
          <span className="nut-value">
            {data[f.key] != null ? Number(data[f.key]).toFixed(1) : '—'}
          </span>
          <span className="nut-label">{f.label}</span>
        </div>
      ))}
    </div>
  )
}
