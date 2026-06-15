/**
 * unitConversion.js — common cooking unit conversions
 *
 * Used during the AI-extracted-recipe guided walkthrough to pre-fill the
 * "Quantity" field: converts a recipe's stated amount (e.g. "2 tbsp") into
 * however many of the chosen USDA portion_unit (e.g. "1 cup") that
 * represents, so the user doesn't have to look up conversions manually.
 */

// "How many base units (ml for volume, g for weight) in one of this unit"
const VOLUME_FACTORS_ML = {
  ml: 1, milliliter: 1, milliliters: 1, millilitre: 1, millilitres: 1,
  l: 1000, liter: 1000, liters: 1000, litre: 1000, litres: 1000,
  tsp: 4.92892, teaspoon: 4.92892, teaspoons: 4.92892,
  tbsp: 14.7868, tablespoon: 14.7868, tablespoons: 14.7868,
  'fl oz': 29.5735, 'fluid ounce': 29.5735, 'fluid ounces': 29.5735, floz: 29.5735,
  cup: 236.588, cups: 236.588,
  pint: 473.176, pints: 473.176,
  quart: 946.353, quarts: 946.353,
  gallon: 3785.41, gallons: 3785.41,
}

const WEIGHT_FACTORS_G = {
  mg: 0.001, milligram: 0.001, milligrams: 0.001,
  g: 1, gram: 1, grams: 1,
  kg: 1000, kilogram: 1000, kilograms: 1000,
  oz: 28.3495, ounce: 28.3495, ounces: 28.3495,
  lb: 453.592, lbs: 453.592, pound: 453.592, pounds: 453.592,
}

function normalizeUnit(unit) {
  return (unit || '').trim().toLowerCase().replace(/\.+/g, '').replace(/\s+/g, ' ')
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
 * Returns null if the units aren't recognized or aren't convertible (e.g.
 * volume vs. weight without a "g" portion_unit) — caller should fall back
 * to the raw extracted quantity in that case.
 */
export function convertToPortionUnits(quantity, fromUnit, portionUnit) {
  if (quantity == null || !fromUnit) return null
  const from = normalizeUnit(fromUnit)
  const { amount: portionAmount, unit: portionUnitName } = parsePortionUnit(portionUnit)

  // "g" portion units represent grams directly, regardless of any leading
  // number — so a weight unit converts straight to grams.
  if (['g', 'gram', 'grams'].includes(portionUnitName)) {
    const fromFactor = WEIGHT_FACTORS_G[from]
    if (fromFactor == null) return null
    return roundQuantity(quantity * fromFactor)
  }

  if (VOLUME_FACTORS_ML[from] != null && VOLUME_FACTORS_ML[portionUnitName] != null) {
    const fromMl = quantity * VOLUME_FACTORS_ML[from]
    const portionMl = portionAmount * VOLUME_FACTORS_ML[portionUnitName]
    return portionMl > 0 ? roundQuantity(fromMl / portionMl) : null
  }

  if (WEIGHT_FACTORS_G[from] != null && WEIGHT_FACTORS_G[portionUnitName] != null) {
    const fromG = quantity * WEIGHT_FACTORS_G[from]
    const portionG = portionAmount * WEIGHT_FACTORS_G[portionUnitName]
    return portionG > 0 ? roundQuantity(fromG / portionG) : null
  }

  return null
}
