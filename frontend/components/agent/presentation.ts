export interface AgentPresentation {
  version: 1;
  kind: "schedule" | "board";
  title: string;
  metrics: { label: string; value: number }[];
  rows: { label: string; detail: string }[];
  warnings: string[];
  next_step: string;
}

export function isAgentPresentation(value: unknown): value is AgentPresentation {
  if (!value || typeof value !== "object") return false;
  const card = value as Record<string, unknown>;
  return card.version === 1 && (card.kind === "schedule" || card.kind === "board")
    && typeof card.title === "string" && typeof card.next_step === "string"
    && Array.isArray(card.metrics) && card.metrics.every(item => item && typeof item.label === "string" && Number.isInteger(item.value) && item.value >= 0)
    && Array.isArray(card.rows) && card.rows.every(item => item && typeof item.label === "string" && typeof item.detail === "string")
    && Array.isArray(card.warnings) && card.warnings.every(item => typeof item === "string");
}
