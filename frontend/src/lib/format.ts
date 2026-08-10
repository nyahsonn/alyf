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

export function formatCostRange(low: number, high: number): string {
  const fmt = (value: number) => `$${value.toLocaleString()}`;
  return low === high ? fmt(low) : `${fmt(low)} – ${fmt(high)}`;
}
