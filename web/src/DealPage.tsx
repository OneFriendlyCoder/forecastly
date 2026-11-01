import { useCallback } from "react";
import { fetchDeal, NotFound } from "./api";
import { Explain } from "./Explain";
import { formatDate, formatMoney, formatScore, riskLevel } from "./format";
import { Reasons } from "./Reasons";
import { ScoreChart } from "./ScoreChart";
import { usePolling } from "./usePolling";

const ACTIVITY: [string, string][] = [
  ["email_sent", "Emails sent"],
  ["email_replied", "Buyer replies"],
  ["meeting_held", "Meetings held"],
  ["meeting_no_show", "Missed meetings"],
  ["contact_added", "Contacts added"],
  ["close_date_changed", "Close date changes"],
];

export function DealPage({ id }: { id: string }) {
  const load = useCallback(() => fetchDeal(id), [id]);
  const { data, error } = usePolling(load, id);

  if (error instanceof NotFound) return <><Back /><h1>Deal not found</h1><p className="notice">There's no deal with the ID {id}.</p></>;
  if (!data) return <><Back /><p className="notice" role={error ? "alert" : undefined}>{error ? "Can't reach the API. Retrying." : "Loading deal…"}</p></>;

  const { deal, scores } = data;
  const risk = deal.score === null ? null : riskLevel(deal.score);
  return (
    <>
      <Back />
      <h1>{deal.deal_id}</h1>
      <p className="lead">{deal.product} · {formatMoney(deal.amount)}{deal.closed ? " · Closed" : ""}</p>
      {error ? <p className="notice" role="alert">Can't reach the API. Showing the last data we received.</p> : null}

      {deal.score === null ? (
        <p className="notice">This deal doesn't have a score yet. Scoring starts 7 days after engagement.</p>
      ) : (
        <div className="grid">
          <section className="card">
            <h2>Win chance</h2>
            <p className="hero" data-testid="score">{formatScore(deal.score)}</p>
            {risk ? <span className={`risk risk-${risk.level}`}>{risk.label}</span> : null}
            <p className="muted">Scored as of {formatDate(deal.as_of!)}</p>
          </section>
          <section className="card">
            <h2>What moved this score</h2>
            <Reasons factors={deal.factors ?? []} />
          </section>
          {deal.closed ? null : <Explain id={deal.deal_id} />}
          <section className="card wide">
            <h2>Win chance over time</h2>
            <ScoreChart scores={scores} />
          </section>
        </div>
      )}

      {deal.activity ? (
        <section className="card activity">
          <h2>Activity so far</h2>
          <dl>
            {ACTIVITY.map(([key, label]) => (
              <div key={key}><dt>{label}</dt><dd>{deal.activity![key]}</dd></div>
            ))}
          </dl>
        </section>
      ) : null}
    </>
  );
}

function Back() {
  return <a className="back" href="#/">← At-risk deals</a>;
}
