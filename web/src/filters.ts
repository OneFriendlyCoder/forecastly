import type { Risk } from "./api";

export const PAGE_SIZE = 25;
export const SORTS = { riskiest: "Riskiest first", biggest_drop: "Biggest score drop", largest: "Largest amount", safest: "Safest first" };

export type Filters = { risk?: Risk; product?: string; owner?: string; q?: string; sort?: string; page?: number };

export function readFilters(hash: string): Filters {
  const params = new URLSearchParams(hash.split("?")[1] ?? "");
  const risk = params.get("risk");
  return {
    risk: risk === "high" || risk === "medium" || risk === "low" ? risk : undefined,
    product: params.get("product") ?? undefined,
    owner: params.get("owner") ?? undefined,
    q: params.get("q") ?? undefined,
    sort: params.get("sort") ?? undefined,
    page: Math.max(Number(params.get("page")) || 1, 1),
  };
}

function toParams(filters: Filters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value && !(key === "page" && value === 1)) params.set(key, String(value));
  }
  return params;
}

/** The address holds the filters, so reloading, sharing a link and the back button all keep them. */
export const filtersToHash = (filters: Filters) => `#/?${toParams(filters)}`;

export function filtersToQuery({ page = 1, ...filters }: Filters) {
  const params = toParams(filters);
  params.set("limit", String(PAGE_SIZE));
  params.set("offset", String((page - 1) * PAGE_SIZE));
  return params.toString();
}

/** The browser reports address changes late, so a quick next click could still see the old filters. */
export function navigate(hash: string) {
  location.hash = hash;
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}
