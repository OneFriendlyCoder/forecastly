import type { DealEvent, Factor } from "./api";

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

export const RISK_LABELS = { high: "High risk", medium: "Medium risk", low: "Low risk" } as const;

export function formatChange(score: number, previous: number | null) {
  if (previous === null) return "New";
  const points = Math.round(score * 100) - Math.round(previous * 100);
  if (points === 0) return "No change";
  return `${points > 0 ? "▲" : "▼"} ${Math.abs(points)} pts`;
}

export function eventText({ event_type: type, payload }: DealEvent): string {
  switch (type) {
    case "email_sent": return "Rep sent an email";
    case "email_replied": return `Buyer replied (${payload.sentiment})`;
    case "meeting_held": return `${capitalise(String(payload.meeting_type))} meeting held`;
    case "meeting_no_show": return `Buyer missed the ${payload.meeting_type} meeting`;
    case "contact_added": return `New contact added: ${String(payload.role).replaceAll("_", " ")}`;
    case "close_date_changed": return `Close date moved from ${formatDate(String(payload.old))} to ${formatDate(String(payload.new))}`;
    case "stage_changed": return `Stage changed to ${payload.to}`;
    case "deal_closed": return `Deal ${payload.outcome}`;
    default: return type;
  }
}

const capitalise = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
