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

export function formatCostRange(low: number, high: number): string {
  const fmt = (value: number) => `$${value.toLocaleString()}`;
  return low === high ? fmt(low) : `${fmt(low)} – ${fmt(high)}`;
}
