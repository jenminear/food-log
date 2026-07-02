/**
 * unitConversion.js — common cooking unit conversions
 *
 * Used during the AI-extracted-recipe guided walkthrough to pre-fill the
 * "Quantity" field: converts a recipe's stated amount (e.g. "2 tbsp") into
 * however many of the chosen USDA portion_unit (e.g. "1 cup") that
 * represents, so the user doesn't have to look up conversions manually.
 */

// "How many base units (ml for volume, g for weight) in one of this unit"
// — includes USDA's internal UN/CEFACT abbreviation codes (mlt, ltr) since
// those occasionally leak through as a portion_unit verbatim.
const VOLUME_FACTORS_ML = {
  ml: 1, mlt: 1, milliliter: 1, milliliters: 1, millilitre: 1, millilitres: 1,
  l: 1000, ltr: 1000, liter: 1000, liters: 1000, litre: 1000, litres: 1000,
  tsp: 4.92892, teaspoon: 4.92892, teaspoons: 4.92892,
  tbsp: 14.7868, tablespoon: 14.7868, tablespoons: 14.7868,
  'fl oz': 29.5735, 'fluid ounce': 29.5735, 'fluid ounces': 29.5735, floz: 29.5735,
  cup: 236.588, cups: 236.588,
  pint: 473.176, pints: 473.176,
  quart: 946.353, quarts: 946.353,
  gallon: 3785.41, gallons: 3785.41,
}

// Includes USDA's internal abbreviation codes (grm, mgm, kgm) for the same
// reason as VOLUME_FACTORS_ML above.
const WEIGHT_FACTORS_G = {
  mg: 0.001, mgm: 0.001, milligram: 0.001, milligrams: 0.001,
  g: 1, grm: 1, gram: 1, grams: 1,
  kg: 1000, kgm: 1000, kilogram: 1000, kilograms: 1000,
  oz: 28.3495, ounce: 28.3495, ounces: 28.3495,
  lb: 453.592, lbs: 453.592, pound: 453.592, pounds: 453.592,
}

// Names that should be treated as "grams" wherever code checks for a
// gram-based portion_unit (e.g. to decide portion_grams should be 1).
// Exported so all call sites share one definition instead of duplicating
// the alias list.
export const GRAM_UNIT_ALIASES = ['g', 'grm', 'gram', 'grams']

export function isGramUnit(unit) {
  return GRAM_UNIT_ALIASES.includes((unit || '').trim().toLowerCase())
}

// Approximate density (grams per ml) for common ingredient categories —
// used ONLY as a last resort, when a recipe gives a volume (e.g. "0.25 tsp")
// but the resolved USDA/OFF entry's portion is a weight ("g"), so there's no
// unit-only conversion available. These are rough culinary-reference values
// (the same ballpark a cook would recall or look up), not exact for any
// specific brand/product — every conversion using this table is flagged as
// an estimate to the user. Checked in order; first matching keyword wins,
// so more specific entries (e.g. "kosher salt") are listed before generic
// ones ("salt").
const DENSITY_G_PER_ML = [
  // very salt/sugar-like granular solids — density varies a lot by brand/grain
  [/kosher salt/, 0.55],
  [/sea salt|table salt|\bsalt\b/, 0.95],
  [/brown sugar/, 0.9],
  [/powdered sugar|confectioners sugar/, 0.56],
  [/granulated sugar|white sugar|\bsugar\b/, 0.85],
  [/baking (soda|powder)/, 0.9],
  [/all.purpose flour|\bflour\b/, 0.53],
  [/cocoa powder/, 0.5],
  [/uncooked rice|\brice\b/, 0.85],
  [/cornstarch|corn starch/, 0.6],
  // fats/oils
  [/olive oil|vegetable oil|canola oil|\boil\b/, 0.92],
  [/melted butter|\bbutter\b/, 0.96],
  [/honey|maple syrup|corn syrup|\bsyrup\b/, 1.4],
  // water-like liquids (juice, milk, broth, vinegar, most chopped/minced
  // fresh produce) — close enough to water's 1g/ml to use as the default
  [/milk|cream|broth|stock|vinegar|juice|water|wine/, 1.0],
  [/onion|garlic|pepper|tomato|herb|cilantro|parsley|scallion|celery|carrot/, 0.4],
]

// Default density for chopped/minced fresh produce and herbs not matched
// above — they're mostly air + water by volume, much lighter than water by
// the cupful.
const DEFAULT_PRODUCE_DENSITY = 0.4

function estimateDensityGPerMl(ingredientName) {
  const name = (ingredientName || '').toLowerCase()
  for (const [pattern, density] of DENSITY_G_PER_ML) {
    if (pattern.test(name)) return density
  }
  return null
}

function normalizeUnit(unit) {
  return (unit || '').trim().toLowerCase().replace(/\.+/g, '').replace(/\s+/g, ' ')
}

// Recipes often give container sizes as a compound unit string, e.g.
// "2 (12oz) cans" -> quantity=2, unit="12oz. cans" — the weight is already
// right there in the unit text, no density guess needed. Expands that into
// an equivalent plain quantity+unit (e.g. 2 x "12oz cans" -> 24 "oz")
// before the normal conversion logic runs. No-ops if `unit` doesn't look
// like "<number><weight/volume unit> <container word>".
const CONTAINER_WORDS = /^(cans?|jars?|bags?|boxes?|packages?|pkgs?|containers?|bottles?)$/
const CONTAINER_UNIT_RE =
  /^([\d.]+)\s*-?\s*(fl\.?\s?oz|fluid\s?ounces?|ounces?|oz|pounds?|lbs?|kilograms?|kg|grams?|g|milliliters?|millilitres?|ml|liters?|litres?|l)\.?\s+(.+)$/

function expandContainerUnit(quantity, unit) {
  if (quantity == null || !unit) return { quantity, unit }
  const m = unit.trim().toLowerCase().match(CONTAINER_UNIT_RE)
  if (!m) return { quantity, unit }
  const [, numStr, perContainerUnit, rest] = m
  if (!CONTAINER_WORDS.test(rest.trim())) return { quantity, unit }
  const perContainerAmount = parseFloat(numStr)
  if (!perContainerAmount) return { quantity, unit }
  return { quantity: quantity * perContainerAmount, unit: perContainerUnit }
}

// Split a portion_unit string like "1 cup" into { amount: 1, unit: "cup" };
// "g" -> { amount: 1, unit: "g" }.
function parsePortionUnit(portionUnit) {
  const text = normalizeUnit(portionUnit)
  const match = text.match(/^([\d.]+(?:\/[\d.]+)?)\s*(.*)$/)
  if (!match) return { amount: 1, unit: text }
  const [, numStr, rest] = match
  let amount = 1
  if (numStr) {
    if (numStr.includes('/')) {
      const [num, den] = numStr.split('/').map(Number)
      amount = den ? num / den : 1
    } else {
      amount = parseFloat(numStr) || 1
    }
  }
  return { amount, unit: rest.trim() || text }
}

function roundQuantity(value) {
  return Math.round(value * 1000) / 1000
}

/**
 * Convert `quantity` of `fromUnit` (as extracted from a recipe, e.g. "tbsp")
 * into however many `portionUnit`s (e.g. "1 cup") that represents.
 * `portionGrams` is the resolved ingredient's actual weight for one
 * `portionUnit` (e.g. USDA says "1 cup" of butter = 227g) — passing it
 * lets us convert any WEIGHT-stated recipe amount (g/oz/lb/kg) against
 * ANY portion, no matter how it's labeled ("1 cup", "1 cup, crumbled",
 * etc.), without needing to recognize the portion's name at all: grams
 * are grams. Before this, a weight-stated quantity against a
 * non-gram-named portion (e.g. "40g" of butter, portion "1 cup") had no
 * conversion path and silently fell back to the raw, unconverted number.
 *
 * Returns `{ value, estimated }` where `estimated` is true if the result
 * relied on an approximate ingredient density (volume -> weight) rather
 * than an exact conversion — callers should flag estimated results so
 * the user knows to double-check them. Returns null if no conversion
 * (exact or estimated) was possible at all — caller should fall back to
 * the raw extracted quantity in that case.
 */
export function convertToPortionUnits(quantity, fromUnit, portionUnit, portionGrams, ingredientName) {
  if (quantity == null || !fromUnit) return null
  ;({ quantity, unit: fromUnit } = expandContainerUnit(quantity, fromUnit))
  const from = normalizeUnit(fromUnit)
  const { amount: portionAmount, unit: portionUnitName } = parsePortionUnit(portionUnit)
  const portionIsGrams = isGramUnit(portionUnitName)

  // Weight -> any portion with a known gram weight (exact — grams are
  // grams regardless of what the portion is called).
  if (WEIGHT_FACTORS_G[from] != null && portionGrams > 0) {
    const fromG = quantity * WEIGHT_FACTORS_G[from]
    return { value: roundQuantity(fromG / portionGrams), estimated: false }
  }

  // Volume -> volume (exact, unit-only — e.g. tbsp -> cups).
  if (VOLUME_FACTORS_ML[from] != null && VOLUME_FACTORS_ML[portionUnitName] != null) {
    const fromMl = quantity * VOLUME_FACTORS_ML[from]
    const portionMl = portionAmount * VOLUME_FACTORS_ML[portionUnitName]
    return portionMl > 0 ? { value: roundQuantity(fromMl / portionMl), estimated: false } : null
  }

  // Volume -> weight ("g" portion): no exact conversion exists (it depends
  // on the ingredient's density), so fall back to an approximate density
  // looked up by ingredient name, and flag the result as an estimate.
  if (portionIsGrams && VOLUME_FACTORS_ML[from] != null) {
    const density = estimateDensityGPerMl(ingredientName) ?? DEFAULT_PRODUCE_DENSITY
    const fromMl = quantity * VOLUME_FACTORS_ML[from]
    return { value: roundQuantity(fromMl * density), estimated: true }
  }

  return null
}

// ---------------------------------------------------------------------------
// Outlier guard — catches the kind of mistake that quietly skews a whole
// week's totals (e.g. typing "150" into a field that meant "1 medium" or
// "1 cup", landing 100x too high). Checked at the moment a quantity is
// entered, not after the fact.
// ---------------------------------------------------------------------------

export const HIGH_CALORIE_THRESHOLD = 500

// kcal this quantity of this ingredient actually contributes.
export function computeCalories(caloriesPer100g, portionGrams, quantityMultiple) {
  if (caloriesPer100g == null || portionGrams == null || quantityMultiple == null) return null
  return caloriesPer100g * (portionGrams / 100) * quantityMultiple
}

export function isHighCalorieOutlier(caloriesPer100g, portionGrams, quantityMultiple) {
  const kcal = computeCalories(caloriesPer100g, portionGrams, quantityMultiple)
  return kcal != null && kcal > HIGH_CALORIE_THRESHOLD
}
