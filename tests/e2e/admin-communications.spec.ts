import { expect, test, type Page, type Route } from "@playwright/test";
import { adminTestUrl } from './admin-fixture-url';

const permissions = ["admin.settings.read", "admin.settings.manage", "admin.alerts.read", "admin.alerts.manage"];
function snapshot() {
  return {
    version: 1, encryption_ready: true,
    channels: {
      sms: { version: 7, enabled: true, provider_id: "kavenegar", ready: true, config: { sender: "10004346", template_id: "" }, credentials: { configured: true, masked: "••••" } },
      voip: { version: 3, enabled: false, provider_id: "none", ready: false, config: {}, credentials: { configured: false, masked: null } },
    },
    call_policy: { version: 4, enabled: false, critical_only: true, persist_seconds: 60, max_attempts: 1, cooldown_seconds: 900, max_calls_per_day: 3,
      quiet_hours: { enabled: true, start: "22:00", end: "08:00", timezone: "Asia/Tehran", critical_bypass: false } },
    provider_catalog: [
      { id: "kavenegar", label: "کاوه‌نگار", channels: ["sms"], config_fields: [{ key: "sender", label: "خط ارسال پیامک", type: "text" }], credential_fields: [{ key: "api_key", label: "کلید دسترسی", type: "secret", required: true }] },
      { id: "asterisk_ari", label: "مرکز تماس استریسک / ایزابل", channels: ["voip"], config_fields: [{ key: "endpoint", label: "نشانی امن سرویس تماس", type: "url", required: true }, { key: "trunk", label: "مسیر خروجی تماس", type: "text", required: true }], credential_fields: [{ key: "username", label: "نام کاربری سرویس", type: "secret", required: true }, { key: "password", label: "رمز سرویس", type: "secret", required: true }] },
    ],
    test_recipients: [{ id: 1, label: "مخاطب آزمون", phone_masked: "***1234", consented: true }],
  };
}

async function realPanel(page: Page, rights = permissions, history?: (route: Route, offset: number) => Promise<void>) {
  let state = snapshot();
  const writes: { path: string; body: Record<string, unknown>; csrf?: string }[] = [];
  let failWrite = false;
  await page.route("**/api/admin/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/admin", "");
    if (path === "/auth/me") return route.fulfill({ json: { admin: { id: 1, username: "test_operator", full_name: "مدیر آزمون", email: "test@example.test", roles: ["operator"], permissions: rights, must_change_password: false, mfa_enabled: false, mfa_required: false, session_expires_at: "2099-01-01T00:00:00Z" } } });
    if (path === "/auth/csrf") return route.fulfill({ json: { csrf_token: "communications-test-csrf" } });
    if (request.method() === "GET" && path === "/communications") return route.fulfill({ json: state });
    if (request.method() === "GET" && path === "/communications/deliveries") return history
      ? history(route, Number(new URL(request.url()).searchParams.get("offset")) || 0)
      : route.fulfill({ json: { items: [], total: 0 } });
    if (request.method() !== "GET") {
      const body = request.postDataJSON() ?? {};
      writes.push({ path, body, csrf: request.headers()["x-csrf-token"] });
      if (path === "/auth/reauthenticate") return route.fulfill({ json: { ok: true } });
      if (failWrite) return route.fulfill({ status: 409, json: { detail: "Reload required" } });
      if (path === "/communications/channels/sms") {
        expect(body.expected_version).toBe(state.channels.sms.version);
        state.channels.sms = { ...state.channels.sms, ...body, version: state.channels.sms.version + 1 };
        return route.fulfill({ json: state.channels.sms });
      }
      if (path === "/communications/call-policy") {
        expect(body.expected_version).toBe(state.call_policy.version);
        state.call_policy = { ...state.call_policy, ...body, version: state.call_policy.version + 1 };
        return route.fulfill({ json: state.call_policy });
      }
      if (path === "/communications/test-events") return route.fulfill({ status: 201, json: { event_id: 1, status: body.mode === "send" ? "queued" : "dry_run", dry_run: body.mode !== "send" } });
    }
    return route.fulfill({ status: 404, json: { detail: "Unexpected test route" } });
  });
  await page.goto(adminTestUrl('/#/communications'));
  await expect(page.getByRole("heading", { name: "پیامک و تماس", exact: true })).toBeVisible();
  return { writes, fail: () => { failWrite = true; }, recover: () => { failWrite = false; } };
}

async function approve(page: Page, confirmation = "") {
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("رمز فعلی مدیر", { exact: true }).fill("fixture-password");
  if (confirmation) await dialog.getByLabel("برای تأیید، عبارت زیر را وارد کنید").fill(confirmation);
  await dialog.getByRole("button", { name: "تأیید و ادامه" }).click();
}

test("local preview has no admin transport, supports dry run and fits the viewport", async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  const apiCalls: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/**", (route) => { apiCalls.push(route.request().url()); return route.abort(); });
  await page.goto(adminTestUrl('/communications-preview.html'));
  await expect(page.getByText("حالت نمایشی", { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "شمارهٔ آزمون", exact: true }).selectOption("1");
  await expect(page.getByRole("button", { name: "ارسال آزمون واقعی" })).toBeDisabled();
  await page.getByRole("button", { name: "ارزیابی بدون ارسال", exact: true }).click();
  await expect(page.getByText("نتیجهٔ ارزیابی بدون ارسال", { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
  await page.getByRole("button", { name: "شماره‌های آزمون", exact: true }).click();
  await expect(page.getByLabel("شمارهٔ همراه", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "شرایط تماس", exact: true }).click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: testInfo.outputPath(`admin-communications-${testInfo.project.name}.png`), fullPage: true });
  expect(apiCalls).toEqual([]);
  expect(errors).toEqual([]);
});

test("preview save uses independent revisions and never asks for real admin credentials", async ({ page }) => {
  await page.goto(adminTestUrl('/communications-preview.html'));
  for (const sender of ["10004346", "10004347"]) {
    await page.getByLabel("خط ارسال پیامک", { exact: false }).fill(sender);
    await page.getByRole("button", { name: "ذخیرهٔ اتصال" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByLabel("رمز فعلی مدیر")).toHaveCount(0);
    await dialog.getByLabel("برای تأیید، عبارت زیر را وارد کنید").fill("ENABLE SMS");
    await dialog.getByRole("button", { name: "تأیید و ادامه" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByLabel("خط ارسال پیامک", { exact: false })).toHaveValue(sender);
  }
  await page.getByRole("button", { name: "ذخیرهٔ شرایط", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "تأیید و ادامه" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("selected channel has a native setup guide and no automatic real send", async ({ page }) => {
  const requests: string[] = [];
  await page.route('**/api/**', route => { requests.push(route.request().url()); return route.abort(); });
  await page.goto(adminTestUrl('/communications-preview.html'));
  const guide = page.locator('details.comms-setup-guide');
  await expect(guide).not.toHaveAttribute('open');
  await guide.locator('summary').filter({ hasText: 'راهنمای اتصال پیامک' }).click();
  await expect(guide).toHaveAttribute('open');
  await expect(guide).toContainText('کاوه‌نگار');
  await expect(guide).toContainText('نام الگوی تأیید شماره اختیاری است');
  await expect(guide.locator('ol li')).toHaveCount(5);
  await expect(guide).toContainText('ارزیابی بدون ارسال');
  await page.getByRole('button', { name: /^تماس / }).click();
  await expect(guide).not.toHaveAttribute('open');
  await guide.locator('summary').filter({ hasText: 'راهنمای اتصال تماس' }).click();
  await expect(guide).toHaveAttribute('open');
  await expect(guide).toContainText('HTTPS');
  await expect(guide).toContainText('ARI');
  await expect(guide).toContainText('ترانک');
  await expect(guide).toContainText('زمینه و داخلی');
  await expect(page.getByRole('button', { name: 'ارسال آزمون واقعی', exact: true })).toBeDisabled();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(requests).toEqual([]);
});

test("preview call setup validates routing, stores a fresh secret, then applies the call policy", async ({ page }) => {
  await page.goto(adminTestUrl('/communications-preview.html'));
  await page.getByRole("button", { name: /^تماس / }).click();
  await page.getByLabel("نام کاربری سرویس", { exact: true }).fill("preview_operator");
  await page.getByLabel("رمز سرویس", { exact: true }).fill("preview-only-password");
  await page.getByLabel("نام برنامهٔ تماس", { exact: true }).fill("");
  await page.getByRole("button", { name: "ذخیرهٔ اتصال" }).click();
  await expect(page.getByText("برای مسیر تماس، نام برنامه را وارد کنید؛ یا زمینه و داخلی را با هم پر کنید.", { exact: true })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByLabel("نام برنامهٔ تماس", { exact: true }).fill("alert-playback");
  await page.getByLabel("فعال بودن کانال", { exact: false }).check();
  await page.getByRole("button", { name: "ذخیرهٔ اتصال" }).click();
  await page.getByRole("dialog").getByLabel("برای تأیید، عبارت زیر را وارد کنید").fill("ENABLE VOIP");
  await page.getByRole("dialog").getByRole("button", { name: "تأیید و ادامه" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByLabel("رمز سرویس", { exact: true })).toHaveValue("");
  await page.getByLabel("تماس خودکار در شرایط تعیین‌شده", { exact: false }).check();
  await page.getByRole("button", { name: "ذخیرهٔ شرایط", exact: true }).click();
  await page.getByRole("dialog").getByLabel("برای تأیید، عبارت زیر را وارد کنید").fill("ENABLE VOIP POLICY");
  await page.getByRole("dialog").getByRole("button", { name: "تأیید و ادامه" }).click();
  await expect(page.getByText("قانون فعال", { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "شمارهٔ آزمون", exact: true }).selectOption("1");
  await expect(page.getByRole("button", { name: "ارسال آزمون واقعی" })).toBeDisabled();
});

test("test recipient requires explicit consent and remains masked after creation", async ({ page }) => {
  await page.goto(adminTestUrl('/communications-preview.html'));
  await page.getByRole("button", { name: "شماره‌های آزمون", exact: true }).click();
  await page.getByLabel("نام مخاطب", { exact: true }).fill("مخاطب نمایشی تازه");
  await page.getByLabel("شمارهٔ همراه", { exact: true }).fill("09120001234");
  await page.getByRole("button", { name: "ثبت شمارهٔ آزمون", exact: true }).click();
  await expect(page.getByText("رضایت صاحب شماره برای آزمون لازم است.", { exact: true })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByLabel("صاحب این شماره برای پیامک یا تماس آزمون رضایت دارد.", { exact: true }).check();
  await page.getByRole("button", { name: "ثبت شمارهٔ آزمون", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "تأیید و ادامه" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator("article").filter({ hasText: "مخاطب نمایشی تازه" })).toContainText("1234");
  await expect(page.getByLabel("شمارهٔ همراه", { exact: true })).toHaveValue("");
  await expect(page.getByText("09120001234", { exact: true })).toHaveCount(0);
});

test("read-only admin cannot mutate, test, or read delivery history without its permission", async ({ page }) => {
  const { writes } = await realPanel(page, ["admin.settings.read"]);
  await expect(page.getByRole("combobox", { name: "ارائه‌دهنده", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "ذخیرهٔ اتصال" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "ارسال آزمون واقعی" })).toHaveCount(0);
  await page.getByRole("button", { name: "پیگیری ارسال", exact: true }).click();
  await expect(page.getByText("دسترسی به تاریخچهٔ ارسال ندارید.", { exact: true })).toBeVisible();
  expect(writes).toEqual([]);
});

test("provider writes reauthenticate, use channel revision and CSRF, and retain blank credentials", async ({ page }) => {
  const { writes } = await realPanel(page);
  await page.getByLabel("خط ارسال پیامک", { exact: false }).fill("10004347");
  await page.getByRole("button", { name: "ذخیرهٔ اتصال" }).click();
  await approve(page, "ENABLE SMS");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(writes.map((entry) => entry.path)).toEqual(["/auth/reauthenticate", "/communications/channels/sms"]);
  expect(writes.every((entry) => entry.csrf === "communications-test-csrf")).toBe(true);
  expect(writes[1].body).toMatchObject({ expected_version: 7, secret_action: "keep", enabled: true });
  expect(writes[1].body).not.toHaveProperty("secret_value");
});

test("unsaved provider changes prevent a real test and test submission occurs once after confirmation", async ({ page }) => {
  const { writes } = await realPanel(page);
  await page.getByRole("combobox", { name: "شمارهٔ آزمون", exact: true }).selectOption("1");
  const testButton = page.getByRole("button", { name: "ارسال آزمون واقعی" });
  await expect(testButton).toBeEnabled();
  await page.getByLabel("خط ارسال پیامک", { exact: false }).fill("10004347");
  await expect(testButton).toBeDisabled();
  await page.getByRole("button", { name: "بازخوانی وضعیت", exact: true }).click();
  await expect(testButton).toBeEnabled();
  await testButton.click();
  await approve(page, "SEND TEST");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const calls = writes.filter((entry) => entry.path === "/communications/test-events");
  expect(calls).toHaveLength(1);
  expect(calls[0].body).toMatchObject({ mode: "send", confirmation: "SEND TEST", recipient_id: 1 });
  expect(String(calls[0].body.client_request_id)).toMatch(/^[0-9a-f-]{36}$/);
});

test("a version conflict blocks resubmission until explicit reload", async ({ page }) => {
  const state = await realPanel(page);
  state.fail();
  await page.getByRole("button", { name: "ذخیرهٔ اتصال" }).click();
  await approve(page, "ENABLE SMS");
  await expect(page.getByText("تنظیمات توسط فرد دیگری تغییر کرده‌اند. ابتدا بازخوانی کنید.", { exact: true })).toBeVisible();
  await expect(page.getByRole("dialog").getByRole("button", { name: "تأیید و ادامه" })).toBeDisabled();
  await page.getByRole("dialog").getByRole("button", { name: "انصراف", exact: true }).click();
  await expect(page.getByRole("button", { name: "ذخیرهٔ اتصال" })).toBeDisabled();
  expect(state.writes.filter((entry) => entry.path === "/communications/channels/sms")).toHaveLength(1);
  state.recover();
  await page.getByRole("button", { name: "بازخوانی وضعیت", exact: true }).click();
  await expect(page.getByRole("button", { name: "ذخیرهٔ اتصال" })).toBeEnabled();
});

test("history paging keeps unsaved credentials and ignores a late previous page", async ({ page }) => {
  let release = () => {};
  let secondStarted = false;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const state = await realPanel(page, permissions, async (route, offset) => {
    expect(new URL(route.request().url()).searchParams.get('limit')).toBe('50');
    if (offset === 50) { secondStarted = true; await pending; }
    const count = offset === 100 ? 1 : 50;
    await route.fulfill({ json: { total: 101, items: Array.from({ length: count }, (_, index) => ({
      id: `manual:${offset + index + 1}`, channel: 'sms', recipient_label: `مخاطب ${offset + index + 1}`,
      phone_masked: '***1234', status: 'cancelled', created_at: '2026-10-21T12:00:00Z', error_code: 'daily_call_cap',
      provider_reference: null,
    })) } }).catch(() => undefined);
  });
  await page.getByLabel('کلید دسترسی', { exact: true }).fill('fixture-key-unsaved');
  await page.getByRole('button', { name: 'پیگیری ارسال', exact: true }).click();
  const pager = page.getByRole('navigation', { name: 'صفحه‌بندی تاریخچه', exact: true });
  await expect(page.getByRole('cell', { name: 'مخاطب 1 ***1234', exact: true })).toBeVisible();
  await expect(page.getByText('سقف تماس روزانه پر شده است.', { exact: true })).toHaveCount(50);
  await pager.getByRole('button', { name: 'بعدی', exact: true }).click();
  await expect.poll(() => secondStarted).toBe(true);
  await pager.getByRole('button', { name: 'بعدی', exact: true }).click();
  await expect(page.getByRole('cell', { name: 'مخاطب 101 ***1234', exact: true })).toBeVisible();
  release();
  await expect(page.getByRole('cell', { name: 'مخاطب 51 ***1234', exact: true })).toHaveCount(0);
  await expect(page.getByLabel('کلید دسترسی', { exact: true })).toHaveValue('fixture-key-unsaved');
  await expect(pager.getByRole('button', { name: 'بعدی', exact: true })).toBeDisabled();
  await pager.getByRole('button', { name: 'قبلی', exact: true }).click();
  await expect(page.getByRole('cell', { name: 'مخاطب 51 ***1234', exact: true })).toBeVisible();
  expect(state.writes).toEqual([]);
});

test("history failure retries independently into an explicit empty page", async ({ page }) => {
  let attempts = 0;
  let recover = false;
  const state = await realPanel(page, permissions, async route => {
    attempts++;
    if (!recover) await route.fulfill({ status: 503, json: { detail: 'History fixture outage' } });
    else await route.fulfill({ json: { items: [], total: 0 } });
  });
  await page.getByLabel('کلید دسترسی', { exact: true }).fill('fixture-key-unsaved');
  await page.getByRole('button', { name: 'پیگیری ارسال', exact: true }).click();
  await expect(page.getByRole('button', { name: 'تلاش دوبارهٔ تاریخچه', exact: true })).toBeVisible();
  const beforeRetry = attempts;
  recover = true;
  await page.getByRole('button', { name: 'تلاش دوبارهٔ تاریخچه', exact: true }).click();
  await expect(page.getByText('هنوز درخواست ارسالی ثبت نشده است.', { exact: true })).toBeVisible();
  await expect(page.getByLabel('کلید دسترسی', { exact: true })).toHaveValue('fixture-key-unsaved');
  const pager = page.getByRole('navigation', { name: 'صفحه‌بندی تاریخچه', exact: true });
  await expect(pager.getByRole('button', { name: 'قبلی', exact: true })).toBeDisabled();
  await expect(pager.getByRole('button', { name: 'بعدی', exact: true })).toBeDisabled();
  expect(attempts).toBe(beforeRetry + 1);
  expect(state.writes).toEqual([]);
});
