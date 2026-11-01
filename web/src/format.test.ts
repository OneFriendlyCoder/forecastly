import { expect, test } from "vitest";
import { eventText, formatChange, formatDate, formatMoney, formatScore, impactText, reasonText } from "./format";

const reason = (feature: string, value: number | string | null) => reasonText({ feature, value, impact: 0 });

test("reasons read as plain sentences", () => {
  expect(reason("days_since_last_reply", 25.48)).toBe("25 days since the last buyer reply");
  expect(reason("negative_replies", 7)).toBe("7 negative replies");
  expect(reason("amount", 5500)).toBe("Deal size of $5,500");
  expect(reason("product", "GTX Basic")).toBe("Product: GTX Basic");
});

test("reasons use the singular for one", () => {
  expect(reason("no_shows", 1)).toBe("1 missed meeting");
  expect(reason("replies_14d", 1)).toBe("1 buyer reply in the last 14 days");
  expect(reason("close_date_pushes", 1)).toBe("Close date pushed 1 time");
});

test("missing and unknown values still produce text", () => {
  expect(reason("days_since_last_reply", null)).toBe("No buyer reply yet");
  expect(reason("something_new", 3)).toBe("something_new: 3");
});

test("impact says which way the score moved", () => {
  expect(impactText(0.4)).toBe("Raises win chance");
  expect(impactText(-0.4)).toBe("Lowers win chance");
});

test("scores, money and dates are formatted", () => {
  expect(formatScore(0.196)).toBe("20%");
  expect(formatMoney(1250)).toBe("$1,250");
  expect(formatDate("2017-12-30T23:59:25+00:00")).toBe("Dec 30, 2017");
});

test("score changes read as points", () => {
  expect(formatChange(0.5, 0.62)).toBe("▼ 12 pts");
  expect(formatChange(0.62, 0.5)).toBe("▲ 12 pts");
  expect(formatChange(0.5, 0.5)).toBe("No change");
  expect(formatChange(0.5, null)).toBe("New");
});

test("events read as plain sentences", () => {
  const text = (event_type: string, payload: Record<string, unknown>) => eventText({ event_id: "1", event_type, occurred_at: "", payload });
  expect(text("email_replied", { sentiment: "negative" })).toBe("Buyer replied (negative)");
  expect(text("meeting_held", { meeting_type: "demo" })).toBe("Demo meeting held");
  expect(text("meeting_no_show", { meeting_type: "pricing" })).toBe("Buyer missed the pricing meeting");
  expect(text("contact_added", { role: "economic_buyer" })).toBe("New contact added: economic buyer");
  expect(text("close_date_changed", { old: "2017-03-01", new: "2017-04-02" })).toBe("Close date moved from Mar 1, 2017 to Apr 2, 2017");
  expect(text("something_new", {})).toBe("something_new");
});
