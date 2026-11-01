import type { Factor } from "./api";

const count = (value: number, one: string, many = `${one}s`) => `${value} ${value === 1 ? one : many}`;

const REASONS: Record<string, (value: number) => string> = {
  days_since_engaged: (v) => `Deal is ${count(Math.round(v), "day")} old`,
  emails_sent_14d: (v) => `${count(v, "email")} sent in the last 14 days`,
  replies_14d: (v) => `${count(v, "buyer reply", "buyer replies")} in the last 14 days`,
  meetings_14d: (v) => `${count(v, "meeting")} held in the last 14 days`,
  days_since_last_reply: (v) => `${count(Math.round(v), "day")} since the last buyer reply`,
  median_reply_hours: (v) => `Buyers usually reply in ${count(Math.round(v), "hour")}`,
  negative_replies: (v) => `${count(v, "negative reply", "negative replies")}`,
  contacts_added: (v) => `${count(v, "buyer contact")} added`,
  buyers_replied: (v) => `${count(v, "buyer")} replied so far`,
  no_shows: (v) => `${count(v, "missed meeting")}`,
  close_date_pushes: (v) => `Close date pushed ${count(v, "time")}`,
  amount: (v) => `Deal size of ${formatMoney(v)}`,
};

const NO_VALUE: Record<string, string> = {
  days_since_last_reply: "No buyer reply yet",
  median_reply_hours: "No buyer reply yet",
};

export function reasonText({ feature, value }: Factor): string {
  if (feature === "product") return `Product: ${value}`;
  if (value === null) return NO_VALUE[feature] ?? `No value for ${feature}`;
  const describe = REASONS[feature];
  return describe ? describe(Number(value)) : `${feature}: ${value}`;
}

// The impact shows what moved the score, not what caused the deal's trouble.
export const impactText = (impact: number) => (impact >= 0 ? "Raises win chance" : "Lowers win chance");

export const formatScore = (score: number) => `${Math.round(score * 100)}%`;

export function formatMoney(amount: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(amount);
}

export function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

// ponytail: fixed cut-offs, tune them once scores are checked against real deals
export function riskLevel(score: number) {
  if (score < 0.4) return { label: "High risk", level: "high" };
  if (score < 0.6) return { label: "Medium risk", level: "medium" };
  return { label: "Lower risk", level: "low" };
}
