export type Factor = { feature: string; value: number | string | null; impact: number };

export type AtRiskDeal = {
  deal_id: string;
  product: string;
  amount: number;
  score: number;
  as_of: string;
  factors: Factor[];
};

export type Deal = {
  deal_id: string;
  product: string;
  amount: number;
  closed: boolean;
  score: number | null;
  as_of: string | null;
  factors: Factor[] | null;
  activity: Record<string, number> | null;
};

export type ScorePoint = { as_of: string; score: number };

export class NotFound extends Error {}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`);
  if (response.status === 404) throw new NotFound();
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  return response.json();
}

export const fetchAtRisk = () => get<{ deals: AtRiskDeal[] }>("/deals/at-risk").then((body) => body.deals);

export async function fetchDeal(id: string) {
  const path = `/deals/${encodeURIComponent(id)}`;
  const [deal, history] = await Promise.all([get<Deal>(path), get<{ scores: ScorePoint[] }>(`${path}/scores?limit=1000`)]);
  return { deal, scores: history.scores };
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
