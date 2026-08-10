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

export function formatCostRange(low: number, high: number): string {
  const fmt = (value: number) => `$${value.toLocaleString()}`;
  return low === high ? fmt(low) : `${fmt(low)} – ${fmt(high)}`;
}
