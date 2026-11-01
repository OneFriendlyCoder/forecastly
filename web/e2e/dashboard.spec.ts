import { expect, test } from "@playwright/test";

// Run with make test-dashboard, which fills the real stack first.
const API = "http://localhost:8080";
const pct = (score: number) => `${Math.round(score * 100)}%`;

test("the at-risk list leads to a matching deal page", async ({ page, request }) => {
  const { deals } = await (await request.get(`${API}/deals/at-risk`)).json();
  const top = deals[0];

  await page.goto("/");
  await expect(page.getByRole("row")).toHaveCount(deals.length + 1);
  await expect(page.getByRole("row").nth(1)).toContainText(top.deal_id);
  await expect(page.getByRole("row").nth(1)).toContainText(pct(top.score));

  await page.getByRole("row").nth(1).getByRole("cell").nth(1).click();
  await expect(page).toHaveURL(new RegExp(`#/deals/${top.deal_id}$`));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(top.deal_id);
  await expect(page.getByTestId("score")).toHaveText(pct(top.score));
  await expect(page.getByRole("img", { name: /Win chance over time/ }).locator("svg path.recharts-line-curve")).toHaveCount(1);

  await page.getByText("Show scores as a table").click();
  const { scores } = await (await request.get(`${API}/deals/${top.deal_id}/scores?limit=1000`)).json();
  await expect(page.locator(".chart-table tbody tr")).toHaveCount(scores.length);
});

test("an unknown deal says so", async ({ page }) => {
  await page.goto("/#/deals/nope");
  await expect(page.getByRole("heading", { name: "Deal not found" })).toBeVisible();
});

test("a malformed address doesn't break the page", async ({ page }) => {
  await page.goto("/#/deals/%");
  await expect(page.getByRole("heading", { name: "Deal not found" })).toBeVisible();
});

test("the chart shows a value on hover", async ({ page, request }) => {
  const { deals } = await (await request.get(`${API}/deals/at-risk`)).json();
  await page.goto(`/#/deals/${deals[0].deal_id}`);
  await page.locator(".recharts-surface").first().hover();
  await expect(page.locator(".chart-tooltip strong")).toHaveText(/^\d+%$/);
});

test("the list shows loading, then an empty message", async ({ page }) => {
  let release = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/deals/at-risk", async (route) => {
    await held;
    await route.fulfill({ json: { deals: [] } });
  });
  await page.goto("/");
  await expect(page.getByText("Loading deals")).toBeVisible();
  release();
  await expect(page.getByText("No deals have been scored yet")).toBeVisible();
});

test("the list reports an API outage and keeps its last data", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("row").nth(1)).toBeVisible();
  await page.route("**/api/**", (route) => route.abort());
  await expect(page.getByRole("alert")).toContainText("Showing the last data", { timeout: 8000 });
  await expect(page.getByRole("row").nth(1)).toBeVisible();
});

test("a first load with the API down says so", async ({ page }) => {
  await page.route("**/api/**", (route) => route.abort());
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("Can't reach the API");
});

test("the agent's answer and its fallback both display", async ({ page, request }) => {
  const { deals } = await (await request.get(`${API}/deals/at-risk`)).json();
  const answers = [
    { grounded: true, answer: { summary: "This deal has gone quiet.", reasons: [{ text: "No replies lately.", feature: "replies_14d" }],
      next_step: { text: "Call the champion.", playbook_id: "a#b" } } },
    { grounded: false, answer: { summary: "These are the facts behind the score.", reasons: [{ text: "replies 14d: 0", feature: "replies_14d" }], next_step: null } },
  ];
  await page.route("**/agent/explain/**", (route) => route.fulfill({ json: answers.shift() }));

  await page.goto(`/#/deals/${deals[0].deal_id}`);
  await page.getByRole("button", { name: "Explain this deal" }).click();
  await expect(page.getByText("Call the champion.")).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Explain this deal" }).click();
  await expect(page.getByRole("alert")).toContainText("plain facts");
});

test("an agent failure offers another try", async ({ page, request }) => {
  const { deals } = await (await request.get(`${API}/deals/at-risk`)).json();
  await page.route("**/agent/explain/**", (route) => route.abort());
  await page.goto(`/#/deals/${deals[0].deal_id}`);
  await page.getByRole("button", { name: "Explain this deal" }).click();
  await expect(page.getByRole("alert")).toContainText("couldn't be reached");
  await expect(page.getByRole("button", { name: "Explain this deal" })).toBeEnabled();
});
