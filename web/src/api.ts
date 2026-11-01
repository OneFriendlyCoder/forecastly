export type Factor = { feature: string; value: number | string | null; impact: number };
export type Risk = "high" | "medium" | "low";

export type DealRow = {
  deal_id: string;
  product: string;
  amount: number;
  owner: string;
  score: number;
  previous_score: number | null;
  risk: Risk;
  as_of: string;
  factors: Factor[];
};

export type RiskTotal = { deals: number; amount: number };

export type Summary = {
  open_deals: number;
  scored_deals: number;
  high: RiskTotal;
  medium: RiskTotal;
  low: RiskTotal;
  products: string[];
  owners: string[];
};

export type Deal = {
  deal_id: string;
  product: string;
  amount: number;
  owner: string;
  closed: boolean;
  score: number | null;
  risk: Risk | null;
  as_of: string | null;
  factors: Factor[] | null;
  activity: Record<string, number> | null;
};

export type ScorePoint = { as_of: string; score: number };
export type DealEvent = { event_id: string; event_type: string; occurred_at: string; payload: Record<string, unknown> };

export class NotFound extends Error {}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`);
  if (response.status === 404) throw new NotFound();
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  return response.json();
}

export async function fetchPipeline(query: string) {
  const [summary, list] = await Promise.all([get<Summary>("/deals/summary"), get<{ total: number; deals: DealRow[] }>(`/deals/at-risk?${query}`)]);
  return { summary, ...list };
}

export async function fetchDeal(id: string) {
  const path = `/deals/${encodeURIComponent(id)}`;
  const [deal, history, recent] = await Promise.all([
    get<Deal>(path),
    get<{ scores: ScorePoint[] }>(`${path}/scores?limit=1000`),
    get<{ events: DealEvent[] }>(`${path}/events?limit=12`),
  ]);
  return { deal, scores: history.scores, events: recent.events };
}

export type Explanation = {
  grounded: boolean;
  answer: {
    summary: string;
    reasons: { text: string; feature: string }[];
    next_step: { text: string; playbook_id: string } | null;
  };
};

export async function explainDeal(id: string): Promise<Explanation> {
  const response = await fetch(`/agent/explain/${encodeURIComponent(id)}`, { method: "POST" });
  if (!response.ok) throw new Error(`Agent returned ${response.status}`);
  return response.json();
}
