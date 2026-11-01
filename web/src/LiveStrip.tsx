import { useEffect, useRef, useState } from "react";
import { fetchLive } from "./api";
import { eventText, formatDate } from "./format";
import { usePolling } from "./usePolling";

const REFRESH_MS = 2000;
const QUIET_AFTER_SECONDS = 10;
const FOLLOW_DEAL = "ALZNZ666"; // in the simulated data, its win chance peaks at 91%, falls to 35% and it stays open

const FLOW = ["Simulated events", "Kafka", "Features", "LightGBM model", "Score", "This dashboard"];

export function LiveStrip() {
  const { data, updatedAt } = usePolling(fetchLive, "live", REFRESH_MS);
  const [rate, setRate] = useState(0);
  const last = useRef<{ events: number; at: number } | undefined>(undefined);

  useEffect(() => {
    if (!data || !updatedAt) return;
    if (last.current && updatedAt > last.current.at) {
      setRate(Math.max(data.events - last.current.events, 0) / ((updatedAt - last.current.at) / 1000));
    }
    last.current = { events: data.events, at: updatedAt };
  }, [updatedAt]);

  if (!data) return null;
  const live = data.seconds_since_update !== null && data.seconds_since_update < QUIET_AFTER_SECONDS;
  return (
    <section className="live" aria-label="Live pipeline activity">
      <div className="live-stats">
        <strong className={live ? "live-on" : "live-off"}>{live ? "● Live" : "○ Waiting for events"}</strong>
        <Stat label="Simulated date" value={data.simulated_at ? formatDate(data.simulated_at) : "—"} />
        <Stat label="Events stored" value={data.events.toLocaleString()} />
        <Stat label="Events a second" value={live ? Math.round(rate).toLocaleString() : "0"} />
        <Stat label="Scores made" value={data.scores.toLocaleString()} />
        <Stat label="Event to score (p95)" value={data.event_to_score_seconds === null ? "—" : `${data.event_to_score_seconds.toFixed(1)}s`} />
        <a className="live-follow" href={`#/deals/${FOLLOW_DEAL}`}>Follow deal {FOLLOW_DEAL} →</a>
      </div>
      <ol className="live-flow">{FLOW.map((stage) => <li key={stage}>{stage}</li>)}</ol>
      {data.recent.length ? (
        <ul className="live-feed">
          {data.recent.map((event) => (
            <li key={event.event_id}>
              <a href={`#/deals/${encodeURIComponent(event.deal_id)}`}>{event.deal_id}</a> {eventText(event)}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return <span className="live-stat"><small>{label}</small>{value}</span>;
}
