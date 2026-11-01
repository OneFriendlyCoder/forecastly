import type { Factor } from "./api";
import { impactText, reasonText } from "./format";

export function Reasons({ factors }: { factors: Factor[] }) {
  return (
    <ul className="reasons">
      {factors.map((factor) => (
        <li key={factor.feature}>
          <span aria-hidden="true" className="arrow">{factor.impact >= 0 ? "↑" : "↓"}</span>
          <span>
            {reasonText(factor)}
            <small>{impactText(factor.impact)}</small>
          </span>
        </li>
      ))}
    </ul>
  );
}
