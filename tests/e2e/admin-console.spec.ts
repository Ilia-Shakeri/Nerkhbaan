import { expect, test, type Page } from "@playwright/test";
import { adminTestUrl } from './admin-fixture-url';

test.beforeEach(async ({ page }) => {
  await page.route('**/*', route => ['localhost', '127.0.0.1'].includes(new URL(route.request().url()).hostname) ? route.continue() : route.abort());
});
const profile = (permissions: string[]) => ({
  id: 1,
  username: "operator_test",
  full_name: "Test Operator",
  email: "operator@example.test",
  roles: ["operator"],
  permissions,
  must_change_password: false,
  mfa_enabled: false,
  mfa_required: false,
  session_expires_at: "2099-01-01T00:00:00Z",
});
const ticket = (id: number) => ({
  id,
  subject: id === 1 ? "First ticket" : "Second ticket",
  status: "open",
  priority: "normal",
  user: { id: 10, username: "test_user" },
  assigned_admin_id: null,
  updated_at: "2026-10-11T00:00:00Z",
});

async function auth(page: Page, permissions: string[]) {
  await page.route("**/api/admin/auth/me", (route) =>
    route.fulfill({ json: { admin: profile(permissions) } }),
  );
  await page.route("**/api/admin/auth/csrf", (route) =>
    route.fulfill({ json: { csrf_token: "test-only-csrf" } }),
  );
  await page.route("**/api/admin/support/assignees", (route) =>
    route.fulfill({ json: { items: [] } }),
  );
}

test("support changes keep the selected ticket and send to its own ID", async ({
  page,
}) => {
  await auth(page, [
    "admin.support.read",
    "admin.support.reply",
    "admin.support.manage",
  ]);
  let releaseFirst: () => void = () => {};
  const firstGate = new Promise<void>((resolve) => {
    releaseFirst = resolve;
  });
  let firstFinished: () => void = () => {};
  const finished = new Promise<void>((resolve) => {
    firstFinished = resolve;
  });
  await page.route("**/api/admin/support/tickets?*", (route) =>
    route.fulfill({ json: { items: [ticket(1), ticket(2)], total: 2 } }),
  );
  await page.route("**/api/admin/support/tickets/1", async (route) => {
    await firstGate;
    await route.fulfill({
      json: {
        ticket: ticket(1),
        messages: [{ id: 1, from: "user", content: "First private body" }],
        internal_notes: [],
      },
    });
    firstFinished();
  });
  await page.route("**/api/admin/support/tickets/2", (route) =>
    route.fulfill({
      json: {
        ticket: ticket(2),
        messages: [{ id: 2, from: "user", content: "Second private body" }],
        internal_notes: [],
      },
    }),
  );
  let replyId = "";
  await page.route("**/api/admin/support/tickets/*/reply", async (route) => {
    replyId = route.request().url().split("/").at(-2) || "";
    expect(route.request().postDataJSON().content).toBe(
      "Reply belongs to second ticket",
    );
    await route.fulfill({
      status: 201,
      json: { message: { id: 3, from: "admin", content: "sent" } },
    });
  });
  await page.goto(adminTestUrl('/#/support'));
  await page.getByRole("button", { name: "Open ticket" }).nth(0).click();
  await page.getByRole("button", { name: "Open ticket" }).nth(1).click();
  await expect(
    page.getByRole("heading", { name: "#2 · Second ticket" }),
  ).toBeVisible();
  releaseFirst();
  await finished;
  await expect(
    page.getByText("Second private body", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("First private body", { exact: true }),
  ).toHaveCount(0);
  await page
    .getByLabel("Reply", { exact: true })
    .fill("Reply belongs to second ticket");
  await page.getByRole("button", { name: "Send reply", exact: true }).click();
  await expect.poll(() => replyId).toBe("2");
});

test("read-only users see no support mutations and can page past the first batch", async ({
  page,
}) => {
  await auth(page, ["admin.support.read"]);
  let requestedOffset = 0;
  await page.route("**/api/admin/support/tickets?*", (route) => {
    const offset = Number(
      new URL(route.request().url()).searchParams.get("offset") || 0,
    );
    requestedOffset = offset;
    return route.fulfill({
      json: { items: [ticket(offset ? 2 : 1)], total: 51 },
    });
  });
  await page.route("**/api/admin/support/tickets/1", (route) =>
    route.fulfill({
      json: { ticket: ticket(1), messages: [], internal_notes: [] },
    }),
  );
  await page.goto(adminTestUrl('/#/support'));
  await page.getByRole("button", { name: "Open ticket" }).click();
  await expect(
    page.getByRole("heading", { name: "#1 · First ticket" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Send reply" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Add note" })).toHaveCount(0);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect.poll(() => requestedOffset).toBe(50);
  await expect(page.getByText("Second ticket", { exact: true })).toBeVisible();
});

test("a failed signout still clears the local profile", async ({ page }) => {
  await auth(page, ["admin.support.read"]);
  await page.route("**/api/admin/support/tickets?*", (route) =>
    route.fulfill({ json: { items: [], total: 0 } }),
  );
  await page.route("**/api/admin/auth/signout", (route) =>
    route.fulfill({ status: 503, json: { detail: "test outage" } }),
  );
  await page.goto(adminTestUrl('/#/support'));
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Sign in", exact: true }),
  ).toBeVisible();
});

test("required MFA hides operational navigation until enrollment", async ({
  page,
}) => {
  await page.route("**/api/admin/auth/me", (route) =>
    route.fulfill({
      json: {
        admin: {
          ...profile(["admin.users.read", "admin.health.read"]),
          mfa_required: true,
        },
      },
    }),
  );
  await page.route("**/api/admin/auth/csrf", (route) =>
    route.fulfill({ json: { csrf_token: "test-only-csrf" } }),
  );
  await page.route("**/api/admin/auth/mfa", (route) =>
    route.fulfill({
      json: { enabled: false, pending: false, backup_codes_remaining: 0 },
    }),
  );
  await page.goto(adminTestUrl('/#/users'));
  await expect(
    page.getByRole("heading", { name: "Authenticator and recovery" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Users", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Start MFA enrollment" }),
  ).toBeVisible();
});

test("a Telegram-only custom role opens source policies without provider or pricing access", async ({
  page,
}) => {
  await auth(page, ["admin.telegram.read"]);
  const requested: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/admin/"))
      requested.push(new URL(request.url()).pathname);
  });
  await page.route("**/api/admin/telegram/sources?*", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: 1,
            source_id: "1",
            channel_id: "-1001234567890",
            display_name: "Test source",
            enabled: true,
            role: "compare",
            parser_type: "strict_explicit",
            allowed_instruments: ["BTC_USD"],
          },
        ],
        recent_rejections: [],
        instrument_ids: ["BTC_USD"],
        total: 1,
      },
    }),
  );
  await page.goto(adminTestUrl('/#/telegram'));
  await expect(
    page.getByRole("heading", { name: "Telegram sources", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Test source", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Edit policy" })).toHaveCount(
    0,
  );
  await expect(page.getByRole("button", { name: "New source" })).toHaveCount(0);
  expect(
    requested.some(
      (path) => path.includes("/providers") || path.includes("/pricing"),
    ),
  ).toBe(false);
});

test("a dead-letter-only custom role pages without requesting the jobs endpoint", async ({
  page,
}) => {
  await auth(page, ["admin.dlq.read"]);
  const requested: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/admin/"))
      requested.push(new URL(request.url()).pathname);
  });
  await page.route("**/api/admin/jobs/dlq?*", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: 2,
            alert_id: 1,
            channel: "email",
            status: "dead",
            attempt_count: 5,
            last_error: "test delivery failed",
          },
        ],
        total: 51,
      },
    }),
  );
  await page.goto(adminTestUrl('/#/dlq'));
  await expect(
    page.getByRole("heading", {
      name: "Dead-letter queue",
      exact: true,
      level: 2,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "test delivery failed", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Retry", exact: true }),
  ).toHaveCount(0);
  await Promise.all([
    page.waitForRequest(
      (request) =>
        new URL(request.url()).pathname === "/api/admin/jobs/dlq" &&
        new URL(request.url()).searchParams.get("offset") === "50",
    ),
    page.getByRole("button", { name: "Next", exact: true }).click(),
  ]);
  expect(requested).not.toContain("/api/admin/jobs");
});

for (const detail of ["Password is incorrect", "Admin session expired"]) {
  test(`security reauthentication handles ${detail}`, async ({ page }) => {
    await auth(page, []);
    await page.route("**/api/admin/auth/mfa", (route) =>
      route.fulfill({
        json: { enabled: false, pending: false, backup_codes_remaining: 0 },
      }),
    );
    await page.route("**/api/admin/auth/reauthenticate", (route) =>
      route.fulfill({ status: 401, json: { detail } }),
    );
    await page.goto(adminTestUrl('/#/security'));
    await page
      .getByLabel("Current password for sensitive changes", { exact: true })
      .fill("test-only-password");
    await page
      .getByRole("button", { name: "Start MFA enrollment", exact: true })
      .click();
    if (detail === "Admin session expired")
      await expect(
        page.getByRole("heading", { name: "Sign in", exact: true }),
      ).toBeVisible();
    else {
      await expect(
        page.getByRole("heading", {
          name: "Authenticator and recovery",
          exact: true,
        }),
      ).toBeVisible();
      await expect(
        page.getByText("Password is incorrect", { exact: true }),
      ).toBeVisible();
    }
  });
}
