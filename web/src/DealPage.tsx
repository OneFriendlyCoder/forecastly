import { fetchDeal, NotFound, type DealEvent } from "./api";
import { Explain } from "./Explain";
import { eventText, formatDate, formatMoney, formatScore, RISK_LABELS } from "./format";
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
  const { data, error } = usePolling(() => fetchDeal(id), id);

  if (error instanceof NotFound) return <><Back /><h1>Deal not found</h1><p className="notice">There's no deal with the ID {id}.</p></>;
  if (!data) return <><Back /><p className="notice" role={error ? "alert" : undefined}>{error ? "Can't reach the API. Retrying." : "Loading deal…"}</p></>;

  const { deal, scores, events } = data;
  return (
    <>
      <Back />
      <div className="deal-header">
        <div>
          <h1>{deal.deal_id}</h1>
          <p className="lead">{deal.product} · {formatMoney(deal.amount)} · {deal.owner}{deal.closed ? " · Closed" : ""}</p>
        </div>
        {deal.score !== null ? (
          <div className="deal-score">
            <p className="hero" data-testid="score">{formatScore(deal.score)}</p>
            <div>
              <span>win chance</span>
              {deal.risk ? <span className={`risk risk-${deal.risk}`}>{RISK_LABELS[deal.risk]}</span> : null}
            </div>
          </div>
        ) : null}
      </div>
      {error ? <p className="notice" role="alert">Can't reach the API. Showing the last data we received.</p> : null}

      {deal.score === null ? (
        <p className="notice">This deal doesn't have a score yet. Scoring starts 7 days after engagement.</p>
      ) : (
        <div className="deal-grid">
          <div className="deal-main">
            {deal.closed ? null : <Explain id={deal.deal_id} asOf={deal.as_of!} />}
            <section className="card">
              <h2>What moved this score</h2>
              <Reasons factors={deal.factors ?? []} />
              <p className="note">Scored as of {formatDate(deal.as_of!)}. These show what moved the model, not what caused any trouble.</p>
            </section>
            <section className="card">
              <h2>Win chance over time</h2>
              <ScoreChart scores={scores} />
            </section>
          </div>
          <aside className="deal-side">
            {deal.activity ? <ActivityCounts activity={deal.activity} /> : null}
            <Timeline events={events} />
          </aside>
        </div>
      )}
    </>
  );
}

function ActivityCounts({ activity }: { activity: Record<string, number> }) {
  return (
    <section className="card">
      <h2>Activity so far</h2>
      <dl>
        {ACTIVITY.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{activity[key]}</dd></div>)}
      </dl>
    </section>
  );
}

function Timeline({ events }: { events: DealEvent[] }) {
  return (
    <section className="card">
      <h2>Recent activity</h2>
      {events.length === 0 ? <p className="muted">No activity yet.</p> : (
        <ol className="timeline">
          {events.map((event) => (
            <li key={event.event_id}>
              <span>{eventText(event)}</span>
              <small>{formatDate(event.occurred_at)}</small>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function Back() {
  // history.back() keeps the list's filters. A deal opened from a direct link has nothing to go back to.
  return <button className="back" onClick={() => (history.length > 1 ? history.back() : (location.hash = "#/"))}>← Back to pipeline</button>;
}
