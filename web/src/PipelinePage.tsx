import { useEffect, useState } from "react";
import { fetchPipeline, type DealRow, type Risk, type Summary } from "./api";
import { filtersToHash, filtersToQuery, navigate, PAGE_SIZE, SORTS, type Filters } from "./filters";
import { formatChange, formatDate, formatMoney, formatScore, reasonText, RISK_LABELS } from "./format";
import { usePolling } from "./usePolling";

const LEVELS: Risk[] = ["high", "medium", "low"];
const LEVEL_HELP = { high: "Under 40% win chance", medium: "40–59% win chance", low: "60% or more" };

export function PipelinePage({ filters }: { filters: Filters }) {
  const query = filtersToQuery(filters);
  const { data, error } = usePolling(() => fetchPipeline(query), query);
  const update = (change: Partial<Filters>) => navigate(filtersToHash({ ...filters, page: 1, ...change }));
  const filtered = Boolean(filters.risk || filters.product || filters.owner || filters.q);

  return (
    <>
      <div className="page-title">
        <div>
          <h1>Pipeline</h1>
          <p className="lead">Which open deals need attention, and why.</p>
        </div>
        {data ? <p className="coverage">{data.summary.scored_deals.toLocaleString()} of {data.summary.open_deals.toLocaleString()} open deals scored</p> : null}
      </div>

      {error ? <p className="notice" role="alert">Can't reach the API. {data ? "Showing the last data we received." : "Retrying."}</p> : null}
      {!data && !error ? <p className="notice">Loading deals…</p> : null}

      {data ? (
        <>
          <RiskCards summary={data.summary} active={filters.risk} onPick={(risk) => update({ risk: risk === filters.risk ? undefined : risk })} />
          <Toolbar filters={filters} summary={data.summary} update={update} filtered={filtered} />
          {data.deals.length === 0 ? (
            <p className="notice">{filtered ? "No deals match these filters." : "No deals have been scored yet."}</p>
          ) : (
            <>
              <DealTable deals={data.deals} />
              <Pager total={data.total} page={filters.page ?? 1} onPage={(page) => update({ page })} />
            </>
          )}
        </>
      ) : null}
    </>
  );
}

function RiskCards({ summary, active, onPick }: { summary: Summary; active?: Risk; onPick: (risk: Risk) => void }) {
  return (
    <div className="risk-cards">
      {LEVELS.map((level) => (
        <button key={level} className={`risk-card risk-card-${level}`} aria-pressed={active === level} onClick={() => onPick(level)}>
          <span className="risk-card-label">{RISK_LABELS[level]}</span>
          <strong>{summary[level].deals.toLocaleString()}</strong>
          <span>{formatMoney(summary[level].amount)} in deals</span>
          <small>{LEVEL_HELP[level]}</small>
        </button>
      ))}
    </div>
  );
}

function Toolbar({ filters, summary, update, filtered }: {
  filters: Filters; summary: Summary; update: (change: Partial<Filters>) => void; filtered: boolean;
}) {
  const [search, setSearch] = useState(filters.q ?? "");
  useEffect(() => setSearch(filters.q ?? ""), [filters.q]);
  useEffect(() => {
    if (search === (filters.q ?? "")) return;
    const timer = setTimeout(() => update({ q: search || undefined }), 250);
    return () => clearTimeout(timer);
  }, [search]);

  return (
    <div className="toolbar">
      <label className="field grow">Search
        <input type="search" placeholder="Deal ID" value={search} onChange={(event) => setSearch(event.target.value)} />
      </label>
      <Select label="Rep" value={filters.owner} options={summary.owners} onChange={(owner) => update({ owner })} />
      <Select label="Product" value={filters.product} options={summary.products} onChange={(product) => update({ product })} />
      <label className="field">Sort by
        <select value={filters.sort ?? "riskiest"} onChange={(event) => update({ sort: event.target.value })}>
          {Object.entries(SORTS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      {filtered ? <button className="clear" onClick={() => navigate(filtersToHash({ sort: filters.sort }))}>Clear filters</button> : null}
    </div>
  );
}

function Select({ label, value, options, onChange }: { label: string; value?: string; options: string[]; onChange: (value?: string) => void }) {
  return (
    <label className="field">{label}
      <select value={value ?? ""} onChange={(event) => onChange(event.target.value || undefined)}>
        <option value="">All</option>
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  );
}

function DealTable({ deals }: { deals: DealRow[] }) {
  return (
    <div className="table-scroll">
      <table className="deals">
        <thead>
          <tr>
            <th>Deal</th><th>Risk</th><th className="number">Win chance</th><th>Change</th>
            <th>Top reason</th><th>Rep</th><th className="number">Amount</th>
          </tr>
        </thead>
        <tbody>
          {deals.map((deal) => {
            const href = `#/deals/${encodeURIComponent(deal.deal_id)}`;
            const reason = deal.factors[0];
            return (
              <tr key={deal.deal_id} onClick={() => navigate(href)}>
                <td>
                  <a href={href}>{deal.deal_id}</a>
                  <small>{deal.product}</small>
                </td>
                <td><span className={`risk risk-${deal.risk}`}>{RISK_LABELS[deal.risk]}</span></td>
                <td className="number"><strong>{formatScore(deal.score)}</strong></td>
                <td className="muted">{formatChange(deal.score, deal.previous_score)}</td>
                <td>{reason ? <><span aria-hidden="true">{reason.impact >= 0 ? "↑ " : "↓ "}</span>{reasonText(reason)}</> : "—"}</td>
                <td>{deal.owner}</td>
                <td className="number">{formatMoney(deal.amount)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="table-note">Scored as of {formatDate(deals[0].as_of)} or earlier. Scores update as new activity arrives.</p>
    </div>
  );
}

function Pager({ total, page, onPage }: { total: number; page: number; onPage: (page: number) => void }) {
  const pages = Math.max(Math.ceil(total / PAGE_SIZE), 1);
  const first = (page - 1) * PAGE_SIZE + 1;
  return (
    <nav className="pager" aria-label="Pages">
      <span>Showing {first.toLocaleString()}–{Math.min(page * PAGE_SIZE, total).toLocaleString()} of {total.toLocaleString()} deals</span>
      <div>
        <button disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
        <button disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
      </div>
    </nav>
  );
}
