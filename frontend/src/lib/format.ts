export const SYSTEM_LABELS: Record<string, string> = {
  roof: "Roof",
  hvac: "HVAC",
  plumbing: "Plumbing",
  electrical: "Electrical",
  water_heater: "Water heater",
  foundation: "Foundation",
};

export const URGENCY_LABELS: Record<string, string> = {
  next_90_days: "Next 90 days",
  next_2_years: "Next 2 years",
  next_5_years: "Next 5 years",
};

// Roadmap display order -- most urgent first. Matches the order the backend
// already sorts action items into (see extraction/service.py).
export const URGENCY_TIERS = ["next_90_days", "next_2_years", "next_5_years"] as const;

// Generic industry rule-of-thumb lifespans in years, [low, high]. Not derived
// from any report or from this specific unit's make/model/condition -- purely
// a reference range for a typically maintained system of that type. Always
// label UI using this as "typical", never as a measurement or a prediction
// specific to the home being reported on.
export const TYPICAL_LIFESPAN_YEARS: Record<string, [number, number]> = {
  roof: [20, 25],
  hvac: [15, 20],
  plumbing: [40, 70],
  electrical: [30, 40],
  water_heater: [8, 12],
  foundation: [80, 100],
};

// Semantic tone per system condition -- kept separate from the accent color
// (see the visual identity proposal). Tailwind class strings are written out
// in full so the compiler's content scan picks them up.
export const CONDITION_TONE: Record<string, { pill: string; fill: string }> = {
  excellent: { pill: "bg-sage-soft text-sage", fill: "bg-sage" },
  good: { pill: "bg-sage-soft text-sage", fill: "bg-sage" },
  fair: { pill: "bg-ochre-soft text-ochre", fill: "bg-ochre" },
  poor: { pill: "bg-brick-soft text-brick", fill: "bg-brick" },
  not_mentioned: { pill: "bg-surface-sunk text-ink-faint", fill: "bg-ink-faint" },
};

// A bare decimal ("0.60") asks a homeowner to have an intuition for what
// counts as high or low. A word doesn't -- the raw number stays available
// via a tooltip for anyone who wants it (see ConfidenceGauge).
export function confidenceLabel(value: number): "High" | "Medium" | "Low" {
  if (value >= 0.75) return "High";
  if (value >= 0.5) return "Medium";
  return "Low";
}

export function formatCostRange(low: number, high: number): string {
  const fmt = (value: number) => `$${value.toLocaleString()}`;
  return low === high ? fmt(low) : `${fmt(low)} – ${fmt(high)}`;
}
