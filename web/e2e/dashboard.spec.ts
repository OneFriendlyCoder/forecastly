import { expect, test } from "@playwright/test";

// Run with make test-dashboard, which fills the real stack first.
const API = "http://localhost:8080";
const pct = (score: number) => `${Math.round(score * 100)}%`;

test("the at-risk list leads to a matching deal page", async ({ page, request }) => {
  const { deals } = await (await request.get(`${API}/deals/at-risk?limit=25`)).json();
  const top = deals[0];

  await page.goto("/");
  await expect(page.getByRole("row")).toHaveCount(26);
  await expect(page.getByRole("row").nth(1)).toContainText(top.deal_id);
  await expect(page.getByRole("row").nth(1)).toContainText(pct(top.score));

  await page.getByRole("row").nth(1).getByRole("cell").nth(4).click();
  await expect(page).toHaveURL(new RegExp(`#/deals/${top.deal_id}$`));
  await expect(page.locator(".timeline li").first()).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(top.deal_id);
  await expect(page.getByTestId("score")).toHaveText(pct(top.score));
  await expect(page.getByRole("img", { name: /Win chance over time/ }).locator("svg path.recharts-line-curve")).toHaveCount(1);

  await page.getByText("Show scores as a table").click();
  const { scores } = await (await request.get(`${API}/deals/${top.deal_id}/scores?limit=1000`)).json();
  await expect(page.locator(".chart-table tbody tr")).toHaveCount(scores.length);
});

test("risk cards filter the list, and the filter survives a visit to a deal", async ({ page, request }) => {
  const summary = await (await request.get(`${API}/deals/summary`)).json();
  await page.goto("/");
  await page.getByRole("button", { name: /Medium risk/ }).click();
  await expect(page).toHaveURL(/risk=medium/);
  await expect(page.locator(".pager")).toContainText(`of ${summary.medium.deals.toLocaleString("en-US")} deals`);
  await expect(page.locator("tbody .risk-medium")).toHaveCount(25);
  await expect(page.locator("tbody .risk-high")).toHaveCount(0);

  await page.getByRole("button", { name: "Next" }).click();
  await expect(page).toHaveURL(/page=2/);
  await expect(page.locator(".pager")).toContainText("Showing 26–50");

  await page.locator("tbody a").first().click();
  await page.getByRole("button", { name: /Back to pipeline/ }).click();
  await expect(page).toHaveURL(/risk=medium.*page=2/);
  await expect(page.getByRole("button", { name: /Medium risk/ })).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("button", { name: /Low risk/ }).click();
  await expect(page.locator("tbody .risk-medium")).toHaveCount(0);
  await expect(page.locator(".pager")).toContainText("Showing 1–25");
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(page.locator("tbody .risk-high").first()).toBeVisible();
});

test("search, rep and sort work together", async ({ page, request }) => {
  const summary = await (await request.get(`${API}/deals/summary`)).json();
  const { deals } = await (await request.get(`${API}/deals/at-risk?limit=1`)).json();
  await page.goto("/");
  await page.getByPlaceholder("Deal ID").fill(deals[0].deal_id.toLowerCase());
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page.getByPlaceholder("Deal ID").fill("no-such-deal");
  await expect(page.getByText("No deals match these filters")).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();

  await page.getByLabel("Rep").selectOption(summary.owners[0]);
  await expect(page.locator("tbody tr").first()).toContainText(summary.owners[0]);
  await page.getByLabel("Sort by").selectOption("largest");
  const first = (await (await request.get(`${API}/deals/at-risk?sort=largest&limit=1&owner=${encodeURIComponent(summary.owners[0])}`)).json()).deals[0];
  await expect(page.locator("tbody tr").first()).toContainText(first.deal_id);
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
  await page.route("**/api/deals/at-risk*", async (route) => {
    await held;
    await route.fulfill({ json: { deals: [], total: 0 } });
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
  await page.route("**/agent/explain/**", (route) =>
    route.fulfill({ body: JSON.stringify({ step: "Checking recent events" }) + "\n" + JSON.stringify({ result: answers.shift() }) + "\n" }));

  await page.goto(`/#/deals/${deals[0].deal_id}`);
  await page.getByRole("button", { name: "Explain this deal" }).click();
  await expect(page.getByText("Call the champion.")).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Explain this deal" }).click();
  await expect(page.getByRole("alert")).toContainText("plain facts");
});

test("the header shows the brand, and the theme choice survives a reload", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("Forecastly");
  await expect(page.getByRole("link", { name: "Forecastly" })).toBeVisible();
  await expect(page.getByAltText("Outreach")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Dark mode" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.getByRole("button", { name: "Light mode" })).toBeVisible();
});

test("the live strip shows what Postgres holds and leads to the deal to follow", async ({ page, request }) => {
  const live = await (await request.get(`${API}/live`)).json();
  await page.goto("/");
  const strip = page.getByRole("region", { name: "Live pipeline activity" });
  await expect(strip).toContainText(live.events.toLocaleString("en-US"));
  await expect(strip).toContainText("LightGBM model");
  await strip.getByRole("link", { name: /Follow deal/ }).click();
  await expect(page).toHaveURL(/#\/deals\/ALZNZ666$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("ALZNZ666");
});

test("an answer stays on screen when the score changes", async ({ page, request }) => {
  const { deals } = await (await request.get(`${API}/deals/at-risk`)).json();
  const id = deals[0].deal_id;
  const answer = { grounded: true, answer: { summary: "Call the champion.", reasons: [], next_step: null } };
  await page.route("**/agent/explain/**", (route) => route.fulfill({ body: JSON.stringify({ result: answer }) + "\n" }));
  await page.goto(`/#/deals/${id}`);
  await page.getByRole("button", { name: "Explain this deal" }).click();
  await expect(page.getByText("Call the champion.")).toBeVisible();

  await page.route(`**/api/deals/${id}`, async (route) => {
    const response = await route.fetch();
    route.fulfill({ response, json: { ...(await response.json()), as_of: "2030-01-01T00:00:00Z" } });
  });
  await expect(page.getByText("The score has changed since this explanation.")).toBeVisible({ timeout: 8000 });
  await expect(page.getByText("Call the champion.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Explain again" })).toBeVisible();
});

test("an agent that fails partway offers another try", async ({ page, request }) => {
  const { deals } = await (await request.get(`${API}/deals/at-risk`)).json();
  await page.route("**/agent/explain/**", (route) =>
    route.fulfill({ body: JSON.stringify({ step: "Checking recent events" }) + "\n" + JSON.stringify({ error: "OperationalError" }) + "\n" }));
  await page.goto(`/#/deals/${deals[0].deal_id}`);
  await page.getByRole("button", { name: "Explain this deal" }).click();
  await expect(page.getByRole("alert")).toContainText("couldn't be reached");
});

test("an agent failure offers another try", async ({ page, request }) => {
  const { deals } = await (await request.get(`${API}/deals/at-risk`)).json();
  await page.route("**/agent/explain/**", (route) => route.abort());
  await page.goto(`/#/deals/${deals[0].deal_id}`);
  await page.getByRole("button", { name: "Explain this deal" }).click();
  await expect(page.getByRole("alert")).toContainText("couldn't be reached");
  await expect(page.getByRole("button", { name: "Explain this deal" })).toBeEnabled();
});
