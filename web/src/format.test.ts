import { expect, test } from "vitest";
import { formatDate, formatMoney, formatScore, impactText, reasonText, riskLevel } from "./format";

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

test("risk levels change at their cut-offs", () => {
  expect(riskLevel(0.39).level).toBe("high");
  expect(riskLevel(0.4).level).toBe("medium");
  expect(riskLevel(0.6).level).toBe("low");
});
