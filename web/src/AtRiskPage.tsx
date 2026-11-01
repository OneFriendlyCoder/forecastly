import { fetchAtRisk } from "./api";
import { formatDate, formatMoney, formatScore, reasonText, riskLevel } from "./format";
import { usePolling } from "./usePolling";

export function AtRiskPage() {
  const { data: deals, error } = usePolling(fetchAtRisk, "at-risk");
  return (
    <>
      <h1>At-risk deals</h1>
      <p className="lead">Open deals with the lowest chance of winning, riskiest first.</p>
      {error ? <p className="notice" role="alert">Can't reach the API. {deals ? "Showing the last data we received." : "Retrying."}</p> : null}
      {!deals && !error ? <p className="notice">Loading deals…</p> : null}
      {deals?.length === 0 ? <p className="notice">No deals have been scored yet.</p> : null}
      {deals?.length ? (
        <div className="table-scroll">
          <table className="deals">
            <thead>
              <tr>
                <th>Deal</th><th>Product</th><th className="number">Amount</th>
                <th className="number">Win chance</th><th>Risk</th><th>Top reason</th><th>Scored as of</th>
              </tr>
            </thead>
            <tbody>
              {deals.map((deal) => {
                const risk = riskLevel(deal.score);
                const href = `#/deals/${encodeURIComponent(deal.deal_id)}`;
                return (
                  <tr key={deal.deal_id} onClick={() => { location.hash = href; }}>
                    <td><a href={href}>{deal.deal_id}</a></td>
                    <td>{deal.product}</td>
                    <td className="number">{formatMoney(deal.amount)}</td>
                    <td className="number"><strong>{formatScore(deal.score)}</strong></td>
                    <td><span className={`risk risk-${risk.level}`}>{risk.label}</span></td>
                    <td>{deal.factors[0] ? reasonText(deal.factors[0]) : "—"}</td>
                    <td className="muted">{formatDate(deal.as_of)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </>
  );
}
