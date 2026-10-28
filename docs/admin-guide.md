# Administrator guide — 2.8.15

Source candidate **2.8.17**: Telegram channel/group ingestion, typed peer IDs, durable edit/delete handling, bounded recovery and cached-input revalidation. Live acceptance remains at **2.8.15** until the guarded rollout passes. Real Telegram collection remains disabled: no reading account or approved sources are available. [Scope and remaining activation gates](telegram-release-2.8.17-fa.md).

<!-- delivery-docs:2.8.16 -->
> مرور سند: ۲۸اکتبر۲۰۲۶؛ منبع/سند **۲.۸.۱۶**، آخرین نصبِ پذیرفته **۲.۸.۱۵**. راهنما؛ وضع جاری در نقشه. عددها، شکست‌ها و قبولی‌های قدیم، شاهد تازه نیستند. [نقشهٔ جاری و فلوچارت](project-completion-roadmap-fa.md) · [فهرست سندها](documentation-index-fa.md).

Source/docs **2.8.16**; live **2.8.15**. Telegram price sources in this panel are required delivery scope with live acceptance pending. Source CRUD and parser preview do not connect an account by themselves. Read [Telegram setup and remaining group/recovery gates](telegram-ingestion-guide-fa.md) and [current roadmap](project-completion-roadmap-fa.md). SMS, voice and email still need actual configured services and receiver evidence.

Installed 2.8.15 retains the existing administrator flows. Pricing, web/admin assets and live account flows passed their own guarded acceptance. [Release and backup evidence](pricing-release-2.8.15-fa.md).

Pricing quality validation and the bounded USD reference clock: [source policy](source-quality-validation-2026-10-28.md).
The dashboard reference panel has three separate Iranian reference identities.
Gold purity is unconfirmed; BTC/USD and USDT/USD are ratios of same-source
Iranian Toman prices. Read the source last-change clock, age and delayed status.
Daily history has unknown observation hours and may contain gaps. These contracts
are read-only and do not become ordinary alert instruments. See
[reference limits](iranian-references-2026-10-17.md).

The administrator console uses a separate HttpOnly session cookie under
`/api/admin`. Public login does not grant administrator access. Permissions are
checked on every server request; controls also follow the signed-in account's
permissions. System roles are reconciled from the versioned permission catalog.
Custom roles keep their own policy.

## Start and sign in

1. Apply all forward migrations, including `20261011_001_delivery_hardening`.
2. Configure the exact browser origin in `ADMIN_FRONTEND_ORIGIN`. Local default
   is `http://localhost:4174`; `127.0.0.1` is a different origin. Set the proxy
   allowlist, administrator network policy and secure cookies for the target
   environment. Use HTTPS outside local development.
3. Provide the four bootstrap identity fields through protected deployment
   configuration. The bootstrap password must be 14–128 characters with upper
   case, lower case, a digit and a symbol. Bootstrap creates the initial
   super administrator only when none exists. It cannot reset an existing user.
4. Run the API and console. For the console:

   ```powershell
   npm.cmd run dev --workspace=nerkhbaan-admin-web
   ```

5. Sign in; replace the bootstrap password before opening operational pages.
   `My security` also provides ordinary password changes.
6. Enroll MFA from `My security`. Re-authenticate, add the manual setup key to
   a TOTP authenticator, then confirm a current six-digit code. Store the ten
   recovery codes shown once. Neither the secret nor the recovery codes enter
   audit events. Production Compose and `.env.example` default to `ADMIN_MFA_REQUIRED=true`; this requires enrollment for all
   operational pages. Confirm at least one administrator's enrollment before
   enforcing that deployment policy.

The TOTP profile is encrypted with a purpose-specific key derived from the
application signing key. Preserve the signing key in the protected backup
plan. A TOTP code and each recovery code work once. After using a TOTP code at
login or re-authentication, wait for a new code before another sensitive check.
Recovery codes can sign in, re-authenticate, rotate recovery codes and disable
optional MFA when the deployment policy allows it. Required MFA cannot be disabled through the console. Rotating
recovery codes invalidates all previous recovery codes.

### Console on an existing HTTPS host

The default build path is `/`. To serve the console at `https://nerkhbaan.ir/admin/`,
build with `VITE_ADMIN_BASE_PATH=/admin/` and set `ADMIN_FRONTEND_ORIGIN=https://nerkhbaan.ir`.
The origin contains no path. Preserve `/api/admin` for API requests and the administrator
cookie path; use `nerkhbaan.ir` as the cookie domain or leave the domain unset for a host-only cookie.
Production Compose passes the build variable to the administrator image. Rebuild the image
when changing it. The HTTPS proxy must route `/admin/` and its assets to the administrator
frontend while routing `/api/admin/` directly to the API; redirect `/admin` to `/admin/`.
Hash navigation stays inside `/admin/`. This setup uses the existing host certificate and
does not require a separate administrator DNS record.

## Session and mutation contract

- All non-read requests require the exact allowed `Origin`; authenticated
  mutations also require `X-CSRF-Token`. `GET /auth/csrf` returns a stable token
  for the current session, so opening another tab does not break an existing tab.
- `POST /auth/reauthenticate` accepts `password` and optional `mfa_code`.
  Sensitive operations require recent successful re-authentication, then their
  exact typed confirmation. Limits apply to sign-in and sensitive checks.
- Password changes and reset revoke both public and administrator credentials.
  An administrator password change preserves only the verified current
  administrator session. Role policy changes revoke affected administrator
  sessions. Disabling an account closes both session types.
- The final active super administrator cannot lose access. Role assignment,
  account disable and bootstrap share one PostgreSQL transaction lock.
- Session expiry returns 401 and clears the local console profile. Failed
  network signout clears the local profile and reports pending server logout;
  reopening the console retries server logout before restoring a profile.
- 403 means origin, CSRF, permission, password gate, MFA gate or re-authentication
  denied. 409 means a conflicting state/version or protected final administrator.
  422 means invalid input. 429 includes `Retry-After`.

## Console pages

| Page | Available operations |
| --- | --- |
| Operations | DB/Redis state, current snapshot age, missing/stale instruments, refresh heartbeat, actual provider runtime/circuit state, budget usage, backlogs and administrator worker state |
| Users | Search/state filter, paging, details, security events, paged public/admin sessions, close one/all sessions, force password change, enable/disable with reason |
| Access | Administrator list, select a user, replace multiple roles, revoke all roles, close administrator sessions, create/edit/deactivate custom roles and permission sets |
| Support | Search/status/priority/assignee filters, paging, complete conversation and internal notes, reply, status/priority update, assign active support staff or unassign |
| Providers | Runtime configuration draft, before/proposed/impact comparison, pending/applied/rejected history, apply/reject and create a rollback draft |
| Telegram sources | Create/edit source policy, parser/instrument selection, trust/confidence/age/deviation limits, independent-source requirement and parser preview |
| Pricing | Latest quote per instrument, unit/purity, canonical history, raw source quotes, verification records, budget-controlled refresh and anomaly review with quote proof |
| Jobs & DLQ | Status filter, paging, safe errors/details, retry and cancel queued administrator/backfill work, delivery retry/cancel and a separately paged dead-letter queue |
| Settings | Feature defaults, global/instrument/provider/source scopes, stored versions, effective inherited values, edit and reset override |
| Audit | Action/resource/result/actor/date filters, paging, redacted before/after changes and filtered JSON export |
| Alerts | User/state/instrument filters, paging, alert configuration, delivery history and enable/disable with reason |
| مرکز ارتباطات | SMS/PBX connection, encrypted credentials, conditional call policy, owned test recipients, dry-run/confirmed real tests, masked delivery history |
| Backup evidence | Read-only backup/restore manifest state and age; reports `not_configured` when no evidence file is connected |
| My security | Password change, MFA enrollment/confirmation, recovery code replacement and optional MFA disable |

### راهنمای اتصال پیامک و تماس

مسیر پنل: **مرکز ارتباطات**، نشانی `#/communications`. کانال‌ها و سیاست تماس،
پیش‌فرض خاموش‌اند. نصب این صفحه، اثبات ارسال پیامک یا پاسخ تماس نیست. بدون سرویس،
اعتبار و شمارهٔ مجاز، همان حالت خاموش بماند. پیش‌نمایش توسعه در
`/communications-preview.html` دادهٔ نمونه دارد؛ ارسال و اتصال API ندارد.

#### ۱. آماده‌سازی سرور و کلید

1. استقرار عادی و مهاجرت `20261021_001_communications.sql` باید کامل شود.
   این مهاجرت، جدول رمزها، شماره‌های آزمایش و رسیدها را می‌سازد.
2. مسئول استقرار، `COMMUNICATIONS_ENCRYPTION_KEY` را با یک کلید Fernet مستقل
   در تنظیمات محافظت‌شدهٔ سرور بگذارد. همهٔ APIها و کارگر ارسال، همان کلید را بخوانند.
   کلید JWT، رمز کاربر و کلید MFA را به‌جای آن نگذارید. کلید را در مرورگر، پیام،
   مخزن کد یا فایل عمومی نگذارید؛ ساخت خودکار کلید روی سرور وجود ندارد.
3. کلید را جدا از پایگاه، در نسخهٔ پشتیبان امن نگه دارید. بدون همان کلید، رمز سرویس
   و شماره‌های آزمایش قابل بازکردن نیستند. تعویض کلید نیاز به بازرمزگذاری دارد؛
   تغییر سادهٔ متغیر، راه چرخش کلید نیست.
4. مدیر وارد شود؛ تغییر رمز و MFA لازم را تمام کند. در صفحه، آماده‌بودن رمزگذاری
   را ببیند. نبود کلید، اجازهٔ ذخیرهٔ رمز یا روشن‌کردن کانال را نمی‌دهد.

#### ۲. اتصال پیامک کاوه‌نگار

1. مالک، حساب فعال، کلید سرویس، خط ارسال مجاز و اعتبار کافی فراهم کند.
   کلید از [پنل رسمی کاوه‌نگار](https://console.kavenegar.com/) گرفته شود.
2. در بخش پیامک، سرویس **کاوه‌نگار** انتخاب شود. `sender` همان **شماره فرستنده**
   و `api_key` همان **کلید سرویس** است؛ هر دو برای این برنامه لازم‌اند.
3. `template_id` اختیاری است: نام **الگوی تأیید شماره**. اگر تنظیم شد، الگوی تأییدشدهٔ
   حساب باید یک جایگاه کد داشته باشد. این الگو فقط برای OTP است؛ متن هشدار قیمت و
   پیام آزمایش از مسیر ارسال عادی می‌رود. روش‌ها در
   [راهنمای رسمی REST کاوه‌نگار](https://kavenegar.com/rest.html) آمده‌اند.
4. ابتدا با کانال خاموش ذخیره کنید. هنگام جایگزینی، کل کلید نو را وارد کنید.
   ورودی خالی، رمز قبلی را نگه می‌دارد. برای پاک‌کردن، کانال خاموش و تأیید
   `CLEAR SMS SECRET` لازم است.
5. برای روشن‌کردن، دوباره احراز هویت و `ENABLE SMS` را تأیید کنید.
   «آماده» یعنی تنظیمات و رمز معتبرند؛ رسید واقعی سرویس هنوز لازم است.

#### ۳. اتصال مرکز تماس

1. مالک PBX، دسترسی ARI، ترانک خروجی و مسیر پاسخ تماس را از قبل آماده کند.
   این پنل، حساب، PBX، ترانک یا فایل صوتی نمی‌سازد. ایزابل تنها وقتی قابل استفاده است
   که همین رابط ARI و مسیر تماس را پشتیبانی و فعال کرده باشد.
2. سرویس **مرکز تماس استریسک / ایزابل** انتخاب شود:

   | فیلد | مقدار لازم |
   | --- | --- |
   | `endpoint` | نشانی HTTPS مرکز، با مسیر خالی یا `/ari`؛ بدون رمز، query یا fragment |
   | `trunk` | نام ترانک PJSIP آماده؛ نام ساده، بدون URI یا الگوی شماره‌گیری آزاد |
   | `username` و `password` | نام کاربری و رمز ARI؛ هر دو با هم ذخیره شوند |
   | `ari_app` | نام برنامهٔ Stasis موجود؛ اگر این راه انتخاب شد، دو فیلد بعد خالی باشند |
   | `context` و `extension` | هر دو برای مسیر dialplan؛ اگر این راه انتخاب شد، `ari_app` خالی باشد |
   | `caller_id` | شمارهٔ تماس‌گیرنده؛ اختیاری و تابع اجازهٔ ترانک |

3. دقیقاً یکی از دو راه برنامه یا dialplan انتخاب شود. سمت PBX باید پخش صدا و رفتار
   پس از پاسخ را پیاده کرده باشد. درخواست این برنامه فقط کانال تماس را ایجاد می‌کند؛
   جزئیات در [سند رسمی Asterisk Channels](https://docs.asterisk.org/Latest_API/API_Documentation/Asterisk_REST_Interface/Channels_REST_API/#originatewithid) است.
4. گواهی HTTPS و نام میزبان باید معتبر باشند. برای PBX خصوصی، مسئول استقرار فقط
   محدودهٔ لازم را در `COMMUNICATIONS_PRIVATE_PBX_ALLOWLIST` بگذارد؛ پیش‌فرض خالی است.
   loopback، link-local، آدرس metadata و مقصد نامعتبر حتی با این مجوز پذیرفته نیستند.
   گواهی‌سنجی خاموش نمی‌شود؛ IP بررسی‌شده ثابت می‌ماند و redirect دنبال نمی‌شود.
5. نخست خاموش ذخیره کنید؛ سپس احراز هویت و `ENABLE VOIP` لازم است.
   پاک‌کردن رمز با کانال خاموش و `CLEAR VOIP SECRET` انجام شود.

#### ۴. سیاست تماس و شمارهٔ کاربر

1. پس از آماده‌شدن سرویس تماس، سیاست جداگانه فعال و `ENABLE VOIP POLICY` تأیید شود.
2. `critical_only` فقط هشدار بحرانی را اجازه می‌دهد. در این حالت، API هم انتخاب تماس
   برای هشدار عادی را با ۴۲۲ رد می‌کند. `persist_seconds` مدت دوام پیوستهٔ شرط است
   (۰ تا ۳۶۰۰ ثانیه). قیمت تازه، حق مصرف منبع و برقرارماندن شرط، پیش از تماس دوباره سنجیده شوند.
3. `cooldown_seconds` فاصلهٔ تماس‌های همان صاحب است (۳۰ تا ۸۶۴۰۰ ثانیه).
   `max_calls_per_day` سقف روزانهٔ همان صاحب است (۱ تا ۱۰۰)؛ تماس آزمایش هم در آن حساب شود.
4. ساعت سکوت با `quiet_hours.start/end` و زمان تهران تنظیم شود. شروع و پایان برابر مجاز نیست.
   `critical_bypass` تنها با انتخاب روشن مدیر، هشدار بحرانی را از سکوت معاف کند.
5. `max_attempts` این نسخه فقط **۱** است؛ `automatic_retry=false`. پذیرش، خطا یا ابهام،
   تماس دوبارهٔ خودکار نمی‌سازد. شمارش بررسی شرط و گرفتن کار صف، تعداد تماس واقعی نیست.
6. کاربر در تنظیمات اعلان، کد OTP شمارهٔ خودش را بگیرد و تأیید کند؛ سپس پیامک یا تماس
   را در هشدار انتخاب کند. OTP ده دقیقه اعتبار دارد؛ فقط آخرین کدِ مصرف‌نشده برای همان
   صاحب و مقصد پذیرفته شود. صرف قبول درخواست سرویس، شماره را تأیید نمی‌کند؛ خود کد باید درست باشد.
   تیک رضایتِ شمارهٔ آزمایش مدیر، شمارهٔ کاربر را تأیید نمی‌کند.

#### ۵. ارزیابی، آزمون و خاموشی

1. مدیر شمارهٔ تحت اختیار خود را در **گیرندگان آزمایش** با نام و رضایت روشن ثبت کند.
   فقط آخرین چهار رقم برگردد؛ شماره در پایگاه رمز شود. سقف هر مدیر ده شماره است.
2. نخست **ارزیابی بدون ارسال** انجام شود. نتیجه، آماده‌بودن تنظیمات و موانع شناخته‌شده را
   نشان دهد؛ اعتبار حساب، DNS، اتصال PBX، دریافت گوشی یا پاسخ تماس را اثبات نمی‌کند.
3. فقط پس از آماده‌بودن سرویس و اجازهٔ صاحب شماره، آزمون واقعی انجام شود. احراز هویت تازه
   و `SEND TEST` لازم است. درخواست در صف می‌رود؛ خود ذخیرهٔ فرم، پیام یا تماس نمی‌فرستد.
   سقف آزمون: سه کار در انتظار، پنج درخواست در ساعت برای هر مدیر/کانال و صد درخواست
   در ساعت برای هر کانال در کل سامانه. خطای آزمون هم از بودجهٔ ساعت حذف نمی‌شود.
4. در **تاریخچه**، `queued` یعنی در صف، `sending` یعنی مرز ارسال گذشته، و `accepted`
   یعنی سرویس درخواست را پذیرفته است. این وضعیت، دریافت گوشی یا پاسخ تماس نیست.
   `failed` یعنی خطا، `cancelled` یعنی لغو، و `unknown` یعنی نتیجه روشن نیست.
   برای نتیجهٔ نامعلوم، به‌جای تکرار کور، مالک سرویس رسید و گوشی/PBX را بررسی کند.
5. خاموش‌کردن سرویس، کار پرداختیِ هنوز ارسال‌نشده را لغو کند. حذف گیرنده، رضایت و صف
   آزمایش او را بردارد. کار `sending`، پذیرفته‌شده یا نامعلوم را نمی‌توان پس گرفت.
   برای حذف هشدار کاربر هم کارِ هنوز نرفته لغو شود.

دسترسی‌ها: خواندن تنظیمات `admin.settings.read`؛ تغییر اتصال، سیاست و گیرنده
`admin.settings.manage`؛ ساخت آزمون `admin.alerts.manage`؛ تاریخچه `admin.alerts.read`.
نشست مدیر، Origin، CSRF و MFA همان قواعد پنل را دارند. هر کانال و سیاست، نسخهٔ جدا دارند؛
خطای ۴۰۹ یا نتیجهٔ نامعلوم ذخیره، نیاز به بازخوانی دارد. رمز واقعی در GET، خطای اعتبارسنجی
و گزارش تغییر برنگردد. ۴۰۳ را با دسترسی/MFA/احراز هویت/CSRF، ۴۲۲ را با فیلد و شرط،
۴۲۹ را با سقف درخواست، و ۵۰۳ را با کلید رمزگذاری یا آماده‌نبودن سرویس بررسی کنید.

در نبود کلید، اعتبار یا PBX، پنل می‌تواند نصب شود و کانال‌ها خاموش بمانند.
آزمون‌های محلی و پیش‌نمایش، به شمارهٔ واقعی چیزی نفرستاده‌اند. پذیرش تحویل واقعی،
به رسید همان محیط و تأیید گیرنده یا PBX نیاز دارد.

Support sends pin the ticket ID at submission. Switching tickets clears the
draft and old details; late responses cannot populate the newly selected ticket.
Assignees must be active and possess `admin.support.reply`.

Telegram and dead-letter pages have their own permission gates, including custom roles with no provider/job access. Source lists use `limit`/`offset` paging and return the supported instrument IDs.

Telegram parser names are `strict_explicit` and `strict_hashtag`; parser version
is `strict-explicit-3`. Use the marked channel ID (`-100…`) from the actual chat,
not a username guess. Preview uses the same parser source as the worker, checks
explicit units and never writes a price. The source policy still controls age,
trust and independent verification during ingestion.

Provider drafts record the current configuration version. Apply takes a lock,
checks that version and recomputes impact. A stale draft returns 409; create a
new draft from the current policy. A rollback creates another reviewable draft,
not an immediate unreviewed change. Code-level quarantines remain safety limits.

Anomaly review never promotes a quote by itself. Open anomalies can become
reviewed, dismissed or resolved; reviewed anomalies can become dismissed or
resolved. A note of at least three characters is required. Candidate and prior
quote values, units, times and sources are shown before a decision.

Delivery cancellation uses a status check in the same transaction. Queued or
claimed (`processing`) work can cancel before its transition to `sending`.
`sending` or delivered work cannot be recalled and returns 409. Queued backfill
and administrator jobs can cancel; running work returns 409. Retry preserves
attempt history. Completed work is not reset silently.

## Request examples

Paths below are relative to `/api/admin`. JSON values are synthetic placeholders.
Use the signed-in browser console for ordinary operations; never commit real
passwords, session cookies, MFA keys or recovery codes into examples.

| Method/path | Body or query | Permission |
| --- | --- | --- |
| POST `/auth/signin` | `identifier`, `password`, optional `mfa_code` | Assigned active administrator |
| GET `/auth/me`, `/auth/csrf`, `/auth/mfa` | none | Current administrator session |
| POST `/auth/reauthenticate` | `password`, optional `mfa_code` | Current session, CSRF |
| POST `/auth/change-password` | `current_password`, `new_password` | Current session, CSRF |
| POST `/auth/signout` | none | Current session, CSRF |
| POST `/auth/mfa/enroll` | none | Recent re-authentication |
| POST `/auth/mfa/confirm`, `/auth/mfa/disable`, `/auth/mfa/recovery-codes` | `code` | Recent re-authentication |
| GET `/users` | `search`, `active`, `limit`, `offset` | `admin.users.read` |
| GET `/users/{id}` | none | `admin.users.read` |
| GET `/users/{id}/sessions` | `kind=user|admin`, `limit`, `offset` | `admin.users.read` |
| GET `/users/{id}/security-history` | `limit`, `offset` | `admin.users.read` |
| PATCH `/users/{id}/state` | `is_active`, `reason`, `confirmation` | `admin.users.manage`, recent re-authentication |
| POST `/users/{id}/force-password-change` | `confirmation` | `admin.users.manage`, recent re-authentication |
| POST `/users/{id}/sessions/close` | `confirmation` | `admin.sessions.manage`, recent re-authentication |
| POST `/users/{id}/sessions/{kind}/{session}/close` | `confirmation` | `admin.sessions.manage`, recent re-authentication |
| GET `/roles`, `/permissions`, `/administrators` | none | `admin.roles.read` |
| PUT `/administrators/{id}/roles` | `roles` array (may be empty), `confirmation` | `admin.roles.manage`, recent re-authentication |
| POST `/administrators/{id}/sessions/close` | `confirmation` | `admin.sessions.manage`, recent re-authentication |
| POST `/roles` / PUT `/roles/{id}` | `name`, `description`, `permissions`, `is_active`, `confirmation` | `admin.roles.manage`, recent re-authentication |
| GET `/support/tickets` | `search`, `status`, `priority`, `assigned_admin_id`, `limit`, `offset` | `admin.support.read` |
| GET `/support/tickets/{id}`, `/support/assignees` | none | `admin.support.read` |
| PATCH `/support/tickets/{id}` | optional `status`, `priority`, `assigned_admin_id` (null clears assignment) | `admin.support.manage` |
| POST `/support/tickets/{id}/reply` | `content` | `admin.support.reply` |
| POST `/support/tickets/{id}/internal-notes` | `content` | `admin.support.manage` |
| GET `/providers`, `/providers/{id}/impact` | impact accepts `enabled`, `role` | `admin.providers.read` |
| GET `/providers/drafts` | `status`, `limit`, `offset` | `admin.providers.read` |
| POST `/providers/{id}/drafts` | Any allowed provider fields listed below | `admin.providers.manage` |
| POST `/providers/drafts/{id}/apply` | `confirmation` | `admin.providers.manage`, recent re-authentication |
| POST `/providers/drafts/{id}/reject`, `/providers/drafts/{id}/rollback` | none | `admin.providers.manage` |
| GET `/telegram/sources` | none | `admin.telegram.read` |
| POST `/telegram/sources` | source identity, policy, `confirmation` | `admin.telegram.manage`, recent re-authentication |
| PATCH `/telegram/sources/{id}` | changed policy fields, `confirmation` | `admin.telegram.manage`, recent re-authentication |
| POST `/telegram/sources/{id}/preview` | `text` | `admin.telegram.read` |
| GET `/pricing/instruments` | none | `admin.pricing.read` |
| GET `/pricing/instruments/{id}` | `history_limit` | `admin.pricing.read` |
| GET `/pricing/anomalies` | `status`, `limit`, `offset` | `admin.pricing.read` |
| POST `/pricing/anomalies/{id}/review` | `status`, `note` | `admin.pricing.manage` |
| POST `/pricing/instruments/{id}/refresh` | `reason` | `admin.pricing.manage` |
| GET `/jobs` | `status`, `limit`, `offset` | `admin.jobs.read` |
| GET `/jobs/dlq` | `limit`, `offset` | `admin.dlq.read` |
| POST `/jobs/{id}/retry`, `/jobs/backfill/{id}/retry` | none | `admin.jobs.manage` |
| POST `/jobs/{id}/cancel`, `/jobs/backfill/{id}/cancel` | `confirmation` | `admin.jobs.manage`, recent re-authentication |
| POST `/jobs/delivery/{id}/retry` | none | `admin.dlq.manage` |
| POST `/jobs/delivery/{id}/cancel` | `confirmation` | `admin.dlq.manage`, recent re-authentication |
| GET `/settings`, `/settings/effective` | effective accepts `scope_id` | `admin.settings.read` |
| PATCH `/settings/feature-flags/{key}` | `enabled`; derived enable also needs `confirmation` | `admin.settings.manage` |
| PUT `/settings/operational` | `key`, `scope_id`, `value`, `expected_version`, optional `confirmation` | `admin.settings.manage` |
| POST `/settings/operational/reset` | same identity/current value/version, `confirmation` | `admin.settings.manage`, recent re-authentication |
| GET `/audit`, `/audit/export` | `action`, `resource_type`, `result`, `actor_admin_id`, `since`, `until`; list also takes `limit`, `offset` | `admin.audit.read` |
| GET `/alerts` | `user_id`, `active`, `instrument_id`, `limit`, `offset` | `admin.alerts.read` |
| GET `/alerts/{id}` | none | `admin.alerts.read` |
| PATCH `/alerts/{id}/state` | `is_active`, `reason`, `confirmation` | `admin.alerts.manage`, recent re-authentication |
| GET `/health`, `/dashboard`, `/backups/status` | none | `admin.health.read` |

Paginated lists return `items`, `total`, `limit`, `offset`. `/jobs` returns
`admin_jobs`, `backfill_jobs`, `delivery_jobs` and totals per collection. The
three job lists share the selected offset. Audit export returns up to 500
filtered records and a `truncated` flag; narrow the date range when truncated.
All exposed errors and audit data redact credential patterns and personal fields.

Allowed provider draft fields: `enabled`, `role`, `priority`, `trust_score`,
`minimum_interval_seconds`, `operational_ttl_seconds`, `requests_per_minute`,
`requests_per_hour`, `requests_per_day`, `reserved_anomaly_requests`,
`reserved_fallback_requests`. Credential values are never writable through a
provider draft; configured status is computed from the shared settings object.

Operational keys: `comparison_visible`, `derived_fallback_enabled`,
`backfill_enabled`, `telegram_source_enabled`, `anomaly_threshold_percent`,
`canonical_expiry_seconds`, `provider_budget_requests_per_hour`. Provider budget
scopes name a provider; Telegram scopes name a stored source; other scopes name
an instrument. All accept `global`. Scope-specific values override global values;
removing a row restores inherited defaults. `expected_version=0` creates a new
override; subsequent edits must provide the current stored version. Canonical
expiry is 30–172800 whole seconds, anomaly threshold is 0.1–25 percent and hourly
budget is 0–100000 whole requests. Boolean keys require actual JSON booleans.
Administrator frontend visibility remains a deployment control and is read-only.

### Typed confirmations

```text
ENABLE USER {id} / DISABLE USER {id}
FORCE PASSWORD CHANGE {id}
CLOSE USER SESSIONS {id}
CLOSE ADMIN SESSIONS {id}
CLOSE USER SESSION {session_id} / CLOSE ADMIN SESSION {session_id}
SET ADMIN ROLES {id}
CREATE ROLE {name} / UPDATE ROLE {id}
APPLY PROVIDER {provider_id}
CREATE TELEGRAM SOURCE {channel_id}
UPDATE TELEGRAM SOURCE {source_id}
CANCEL ADMIN JOB {id} / CANCEL BACKFILL {id} / CANCEL DELIVERY {id}
CHANGE SETTING {key}:{scope_id}
RESET SETTING {key}:{scope_id}
ENABLE DERIVED FALLBACK
ENABLE ALERT {id} / DISABLE ALERT {id}
```

## Backup status wiring

`ADMIN_BACKUP_STATUS_FILE` must name an absolute path to a small JSON manifest.
Mount only that file read-only in the API container. The API returns only
`last_backup_at`, `last_restore_at`, `backup_status`, `restore_status`, `verified`,
`size_bytes` and computed ages. It never exposes backup paths or permits restore.
The restore drill can write this evidence file using `BACKUP_STATUS_FILE` after
the Timescale restore and fingerprint comparison pass. Local or CI evidence
must not be relabeled as live-host verification.

## Validation and delivery gate

```powershell
Push-Location apps/api
python -m unittest discover -s tests -p 'test_admin*.py'
python -m pyflakes app/admin
Pop-Location
npm.cmd run build --workspace=nerkhbaan-admin-web
npm.cmd run typecheck --workspace=@nerkhbaan/ui
npm.cmd run test:e2e -- tests/e2e/admin-console.spec.ts
```

The administrator suite tests CSRF stability, real HTTP session/MFA checks,
one-use recovery, password/role revocation, final-super-admin protection,
assignment/unassignment, SQL filtering/latest quote selection, draft conflicts,
setting versions/reset, safe errors and worker recovery. The browser suite uses
synthetic responses for ticket races, permissions, paging, logout and required
MFA. Run the full project gates from the release runbook as well. SQLite tests
do not prove PostgreSQL locking under two replicas, live provider correctness,
Docker deployment or live backup recovery; those target-host gates remain part
of the delivery procedure.
