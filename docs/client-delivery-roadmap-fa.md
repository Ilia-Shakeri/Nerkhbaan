# نقشه راه تکمیل و تحویل پروژه نرخ‌بان

**نسخه مبنا:** `2.7.4`  
**تاریخ مبنا:** ۱۴۰۵/۰۶/۲۹ — 2026-09-20  
**وضعیت سند:** مرجع اصلی برنامه تحویل به کارفرما

این سند فقط فهرست آرزوها نیست. هر کار یک خروجی، مسئول، مدرک و شرط قبولی
دارد. پروژه زمانی «قابل تحویل» است که همه موارد P0 بسته شوند؛ نه وقتی فقط
ظاهر سایت خوب باشد یا سرویس در یک لحظه پاسخ `200` بدهد.

---

## 1. وضعیت واقعی امروز

### تأییدشده

- نسخه `2.7.4` روی `nerkhbaan.ir` فعال است.
- API، وب، PostgreSQL و Redis در آخرین بررسی آماده پاسخ بودند.
- دو replica برای API فعال شده است.
- نمودار نقره داده ذخیره‌شده دارد و `chart_error=false` گزارش شده است.
- سه اجرای زمان‌بندی‌شده اخیر price-feed موفق بوده‌اند.
- تست‌های محلی آخرین انتشار: ۲۰۹ تست API پاس، یک تست PostgreSQL محلی به‌دلیل
  نبود `TEST_DATABASE_URL` ردشده، ۳۵ تست قرارداد رابط پاس.
- CI واقعی خود تست PostgreSQL، Redis، migration، restore، مرورگر، Compose،
  اسکن امنیتی و ساخت image را تعریف کرده است.
- صفحات حریم خصوصی، شرایط، کوکی، بازپرداخت و اطلاعات کسب‌وکار وجود دارند.
- فرم‌های حساس رضایت صریح دارند و رضایت از پیش انتخاب نشده است.
- نمودار بیرونی فقط پس از اقدام روشن کاربر بارگذاری می‌شود.
- لاگ ساخت‌یافته، metrics، Prometheus، Grafana و Alertmanager در کد/Compose
  وجود دارند.
- بکاپ محلی production ساخته و فشرده‌بودن آن بررسی شده است.

### هنوز تأییدنشده یا باز

- آخرین CI شاخه `main` قرمز است. شکست‌ها شامل browser E2E، migration checksum،
  Compose validation، اسکن dependency/image و چند image scan است.
- بکاپ خارج از سرور و restore واقعی production هنوز مدرک تأییدشده ندارد.
- فایل خصوصی هشت gate اپراتوری هنوز کامل و معتبر نشده است.
- shared-edge در حال حاضر کار می‌کند؛ ولی bind mount آن در Compose پروژه میزبان
  مشترک ثبت نشده است. recreate کامل edge می‌تواند تنظیم را از دست بدهد.
- چرخش همه رمزها و کلیدهایی که پیش‌تر خارج از secret store استفاده یا ارسال
  شده‌اند، مدرک ندارد.
- منبع مستقیم و تأییدشده برای طلای ۲۴ عیار وجود ندارد.
- USD/Toman واقعی و مستقیم هنوز جایگزین bridge مبتنی بر USDT نشده است.
- نقره ۹۹۹ ایرانی منبع مستقیم تأییدشده ندارد و قیمت Toman آن مشتق می‌شود.
- حقوق بازنشر همه داده‌های بازار، دارایی‌ها و فونت‌ها امضای نهایی ندارد.
- تست کامل صفحه‌خوان، zoom، موبایل، هر دو تم و فرم‌های لاگین‌شده تمام نشده است.
- ۹۴ anomaly در آخرین health snapshot باز بود؛ باید دسته‌بندی و سیاست بستن آن
  روشن شود.
- وضعیت ساعت/NTP، تازگی providerها و topology سرور در روز تحویل باید دوباره
  بررسی شود؛ مدرک انتشار قبلی برای روز تحویل کافی نیست.

---

## 2. تعریف دقیق «پروژه تمام شده»

تحویل امن فقط وقتی انجام می‌شود که همه شروط زیر برقرار باشند:

1. آخرین commit و tag نهایی در CI کاملاً سبز باشد.
2. نسخه staging همان artifact نهایی را اجرا کند و تست پذیرش روی آن پاس شود.
3. لاگین، ثبت‌نام، refresh session، خروج، بازیابی رمز و رضایت‌نامه‌ها پاس شوند.
4. قیمت، تاریخچه و نمودار هر دارایی وضعیت درست `live`، `derived`، `stale` یا
   `unavailable` را صادقانه نشان دهند؛ داده ساختگی یا بی‌منبع نمایش داده نشود.
5. هشدار از ساخت تا trigger و حداقل یک کانال تحویل واقعی اثبات شود.
6. backup خارج از host ساخته و در محیط disposable با زمان ثبت‌شده restore شود.
7. rollback نسخه برنامه و rollback تنظیمات بدون حذف volume تمرین شود.
8. همه رمزها، tokenها و کلیدهای تحویل‌شده چرخانده و در secret store قرار گیرند.
9. حقوق providerها، retention، processorها و متن حقوقی توسط مالک تأیید شوند.
10. تست keyboard، screen reader، zoom 200%، موبایل و contrast پاس شود.
11. runbookهای deploy، incident، backup/restore، provider و NTP کامل باشند.
12. مالکیت repo، دامنه، DNS، VPS، ایمیل، monitoring و backup به حساب‌های
    مورد تأیید کارفرما منتقل یا مستند شود.
13. بسته تحویل بدون secret، داده production، cache و فایل شخصی ساخته و از داخل
    خود بسته دوباره تست شود.
14. صورت‌جلسه پذیرش، محدودیت‌های پذیرفته‌شده و دوره پشتیبانی امضا شود.

---

## 3. اولویت‌ها

| سطح | معنی | قانون |
| --- | --- | --- |
| P0 | blocker تحویل | تا بسته نشود، تحویل نهایی ممنوع |
| P1 | لازم برای کیفیت تجاری | قبل از پایان دوره پذیرش بسته شود |
| P2 | بلوغ و کاهش هزینه آینده | می‌تواند با قرارداد نگهداری ادامه یابد |

---

## 4. برنامه فازبندی‌شده

### فاز 0 — تثبیت مبنا و سبزکردن CI

**زمان:** ۱ تا ۳ روز کاری  
**مالک اصلی:** Engineering + QA  
**اولویت:** P0

#### کارها

- علت دقیق همه jobهای قرمز CI را از log کامل استخراج و ثبت کن.
- browser webServer timeout را بازتولید و رفع کن.
- migration checksum drift را بررسی کن؛ migration قبلی را بی‌دلیل ویرایش نکن.
- Compose validation را با environment نمونه و همه profileها پاس کن.
- vulnerabilityهای HIGH/CRITICAL را رفع، pin یا با استثنای زمان‌دار و دلیل
  مستند مدیریت کن.
- image scanهای API، web، admin و telegram را سبز کن.
- actionهای دارای هشدار runtime قدیمی را به نسخه pinشده پشتیبانی‌شده ارتقا بده.
- `npm.cmd run verify` و CI کامل را روی commit یکسان اجرا کن.
- یک issue برای هر شکست مستقل بساز؛ چند علت را زیر یک عنوان مبهم پنهان نکن.

#### خروجی

- یک commit مبنای سبز.
- لینک اجرای CI سبز.
- گزارش کوتاه علت و رفع هر job.
- صفر تغییر track‌نشده مربوط به انتشار.

#### شرط خروج

- همه jobهای اجباری CI سبز.
- هیچ تست skipشده‌ای بدون دلیل و مالک باقی نماند.
- branch protection اجازه merge با CI قرمز ندهد.

---

### فاز 1 — صحت داده و تصمیم حقوقی providerها

**زمان:** ۳ تا ۱۰ روز کاری؛ وابسته به پاسخ provider/مالک  
**مالک اصلی:** Product Owner + Legal + Pricing Engineering  
**اولویت:** P0

#### کارهای فنی

- برای هر instrument جدول منبع واقعی بساز: provider، واحد، purity، market،
  timestamp، TTL، fallback، حق بازنشر و attribution.
- منبع مستقیم طلای ۱۸ و ۲۴ را جدا نگه دار. تبدیل عیار برای قیمت نهایی ممنوع.
- برای طلای ۲۴ یکی از این دو تصمیم ثبت شود:
  - provider مستقیم معتبر تهیه و با parser/test مستقل فعال شود؛ یا
  - در نسخه تحویل `unavailable` بماند و کارفرما این محدودیت را کتبی بپذیرد.
- برای USD/Toman و نقره ۹۹۹ نیز provider مستقیم تهیه شود یا مشتق‌بودن آن‌ها
  در UI و قرارداد تحویل صریح بماند.
- provider فقط با HTTP 200 تأیید نشود؛ تازگی، واحد، شکل payload، محدوده قیمت،
  شرایط استفاده و رفتار از شبکه production بررسی شود.
- داده stale، ambiguous، ناسازگار با واحد یا دارای ریسک حل‌نشده خاموش بماند.
- attribution هر provider در UI/اسناد طبق مجوز آن اضافه شود.
- anomalyهای باز دسته‌بندی شوند: false positive، provider fault، clock fault،
  parser fault یا price disagreement.

#### کارهای حقوقی و مالک

- تأیید کتبی حقوق دریافت و بازنشر داده بازار.
- فهرست processorها، کشور، قرارداد، retention و مسیر انتقال داده.
- تصمیم درباره نشانی شکایت عمومی و شناسه‌های ثبت/مالیات/مجوز در صورت لزوم.
- ماتریس نگهداری و حذف داده برای حساب، session، chat، support، audit و backup.
- تأیید حقوق لوگو، فونت، تصویر و متن.
- اعلام روشن: خدمت فعلی رایگان و ایران‌محور است. subscription و بازار جهانی
  بدون بازبینی حقوقی و نسخه سیاست تازه فعال نشود.

#### خروجی

- `provider-rights-signoff` معتبر.
- جدول نهایی منابع و limitationهای پذیرفته‌شده.
- متن حقوقی نهایی دوزبانه؛ بدون عبارت draft.
- policy version تازه فقط اگر متن ماهوی تغییر کند.

#### شرط خروج

- هیچ قیمت production بدون source/status/age قابل مشاهده نباشد.
- طلای ۲۴، USD/Toman و نقره ۹۹۹ یا مستقیم باشند، یا محدودیت آن‌ها رسمی پذیرفته شود.
- حقوق بازنشر و attribution هر منبع مدرک داشته باشد.

---

### فاز 2 — امنیت، secret و زیرساخت قابل بازیابی

**زمان:** ۳ تا ۵ روز کاری  
**مالک اصلی:** Platform/Ops + Security  
**اولویت:** P0

#### کارها

- همه credentialهای قبلی را rotate کن: SSH، حساب deploy، دیتابیس، Redis، JWT،
  webhook، relay، provider، monitoring و backup.
- secretها فقط از فایل محافظت‌شده یا secret manager تزریق شوند؛ در Git، log،
  artifact، screenshot یا evidence نباشند.
- shared-edge bind mount، TLS mount و شبکه Nerkhbaan را در Compose پروژه میزبان
  ثبت و با recreate واقعی تست کن.
- محیط staging جدا با DB، Redis، دامنه، webhook، key و volume مستقل بساز.
- monitoring profile را روشن کن و dashboard/alert واقعی را تأیید کن:
  - قیمت expired یا unavailable؛
  - provider failure/circuit؛
  - queue و dead-letter؛
  - Redis memory؛
  - migration drift؛
  - backup age؛
  - HTTP 5xx و latency.
- backup رمزنگاری‌شده را خارج از VPS ایران نگه دار.
- restore کامل PostgreSQL و بازیابی Redis را در محیط disposable تمرین کن.
- مالک کلید backup، rotation، escrow و حالت گم‌شدن کلید را ثبت کن.
- NTP را از خود production تأیید کن؛ بدون ساعت درست، freshness قابل اعتماد نیست.
- firewall، SSH، userها، Docker socket و دسترسی admin دوباره بازبینی شوند.

#### خروجی

- restore report با RPO، RTO، checksum و timestamp.
- secret rotation checklist امضاشده؛ بدون درج مقدار secret.
- staging URL و health proof.
- shared-edge recreate proof.
- dashboard و alert test proof.

#### شرط خروج

- restore واقعی موفق.
- recreate edge بدون ۵۰۲ پایدار یا از دست‌رفتن config.
- secret scan پاک و همه رمزهای قدیمی باطل.
- ساعت production synchronized و مستند.

---

### فاز 3 — تست پذیرش سرتاسری

**زمان:** ۳ تا ۵ روز کاری + حداقل ۲۴ ساعت soak  
**مالک اصلی:** QA + Product Owner  
**اولویت:** P0

#### سناریوهای الزامی

##### حساب و حریم خصوصی

- ثبت‌نام با consent و بدون consent.
- ورود، خروج، refresh، session expiry و reuse rejection.
- تغییر/بازیابی رمز.
- دسترسی عمومی به پنج صفحه حقوقی.
- ثبت receipt نسخه policy.
- مسیر درخواست دسترسی، اصلاح و حذف داده.

##### قیمت و نمودار

- هر چهار کارت و همه timeframeها.
- loading، empty، stale، expired، unavailable و error.
- طلا ۱۸ و ۲۴ با منبع مستقل یا وضعیت unavailable صادقانه.
- نقره و تاریخچه ۳۰روزه.
- consent نمودار بیرونی و عدم درخواست ثالث پیش از consent.
- drag با mouse/touch، keyboard fallback و reduced motion.

##### هشدار و تحویل

- ساخت، ویرایش، حذف و trigger هشدار.
- idempotency؛ یک رویداد، یک تحویل.
- حداقل یک کانال production واقعی.
- retry، rate limit و dead-letter.
- telegram/push/email فقط در صورت قرارداشتن در scope قرارداد.

##### ادمین و امنیت

- role و permission، CSRF، Origin، rate limit و audit trail.
- admin mutationها و dialogهای خطرناک.
- webhook SSRF و secret header.
- آپلود/ورودی بزرگ و خطاهای 401/403/422/429/5xx.

##### دسترسی‌پذیری و دستگاه

- فقط keyboard؛ focus visible و ترتیب منطقی.
- صفحه‌خوان روی login، dashboard، alert، support و legal.
- zoom 200% و 400%.
- موبایل کوچک، تبلت، دسکتاپ و هر دو تم.
- RTL/LTR، متن فارسی/انگلیسی و بدون overflow افقی.
- contrast و alt text.

##### پایداری

- load روی `/api/prices` و WebSocket.
- چند replica و kill یکی از replicaها.
- عدم refresh یا delivery تکراری.
- soak حداقل ۲۴ ساعت برای تحویل؛ ۷۲ ساعت برای سطح ۱۰/۱۰.

#### خروجی

- گزارش پذیرش با pass/fail، screenshot و timestamp.
- defect list صفر برای P0 و بدون P1 بحرانی.
- browser smoke proof معتبر در فایل خصوصی gateها.

#### شرط خروج

- همه سناریوهای P0 پاس.
- کارفرما limitationهای باقی‌مانده را دیده و پذیرفته باشد.

---

### فاز 4 — آماده‌سازی بسته تحویل

**زمان:** ۱ تا ۲ روز کاری  
**مالک اصلی:** Engineering Lead + Product Owner  
**اولویت:** P0

#### محتوای بسته

- source code روی tag نهایی و commit immutable.
- `CHANGELOG.md`، `README.md` و راهنمای توسعه.
- راهنمای نصب staging و production.
- معماری سرویس‌ها و data flow.
- API documentation و فهرست endpointها.
- runbookهای deploy، rollback، backup/restore، Redis، NTP، provider و incident.
- schema/migration و روش ارتقای امن.
- فهرست dependency/licence و NOTICE.
- فایل `.env.example` بدون secret.
- فهرست حساب‌ها و مالکیت‌ها؛ بدون رمز در سند.
- ماتریس provider و محدودیت‌های پذیرفته‌شده.
- تست report، security scan، restore proof و operator evidence reference.
- SHA256 برای artifact نهایی.
- راهنمای فارسی کوتاه برای کارفرما: شروع، توقف، سلامت، بکاپ، restore و تماس اضطراری.

#### پاک‌سازی بسته

- حذف `.env`، private key، token، dump، volume، log، cache و اطلاعات شخصی.
- extract بسته در مسیر تازه.
- نصب از lockfile.
- اجرای migration، تست و build از داخل همان بسته.
- تطبیق manifest و checksum.

#### شرط خروج

- کارفرما بتواند فقط با اسناد بسته، staging را بالا بیاورد.
- هیچ secret یا داده production در artifact نباشد.
- tag نهایی، artifact و checksum با هم تطبیق داشته باشند.

---

### فاز 5 — انتشار نهایی و تحویل رسمی

**زمان:** ۱ روز انتشار + ۳ تا ۷ روز hypercare  
**مالک اصلی:** Product Owner + Ops  
**اولویت:** P0

#### قبل از انتشار

- scope freeze و تأیید release notes.
- backup تازه و off-host.
- CI سبز روی همان commit.
- هشت gate اپراتوری معتبر.
- rollback target و فرمان‌های rollback ثبت‌شده.
- پنجره انتشار و مسئول تصمیم go/no-go مشخص.

#### هنگام انتشار

- همان artifact تست‌شده staging منتشر شود؛ rebuild جدا ممنوع.
- migration فقط با runner رسمی.
- volumeها حذف یا reset نشوند.
- دو replica API حفظ شوند.
- health، header، TLS، login، prices، silver history و channel delivery بررسی شوند.

#### پس از انتشار

- monitoring و error rate در ۱۵ دقیقه، ۱ ساعت، ۲۴ ساعت و ۷۲ ساعت بررسی شود.
- قیمت stale/unavailable و anomalyها بازبینی شوند.
- صورت‌جلسه تحویل، نسخه، commit، tag، checksum و limitationها امضا شود.
- دوره hypercare و SLA پاسخ مشخص شود.

#### شرط پایان پروژه

- فرم پذیرش کارفرما امضا شده است.
- مالکیت‌ها منتقل شده‌اند.
- هیچ P0 باز نیست.
- P1/P2 باقی‌مانده قرارداد و زمان‌بندی جدا دارند.

---

## 5. هشت gate قطعی اپراتوری

مدرک خصوصی از نمونه `docs/operator-gates.evidence.example.json` ساخته شود.
مقدار secret داخل evidence ممنوع است.

| Gate | وضعیت فعلی | کار لازم برای Pass |
| --- | --- | --- |
| حقوق provider | باز | قرارداد/مجوز/تأیید مالک با URI مدرک |
| canary زمان‌بندی‌شده | بخشی | چند اجرای موفق داریم؛ مانیتور و بازه معتبر ثبت شود |
| secret manager | باز | مدرک injection و rotation بدون مقدار secret |
| Navasan transport | باز | proxy HTTPS یا دلیل امضاشده برای خاموش‌ماندن |
| دامنه‌های آینده BRSAPI/TSETMC | باز | مالکیت و تصمیم enable/disable |
| restore production | باز | restore خارج از host با RTO/RPO |
| deployment production | بخشی | health proof تازه در قالب evidence خصوصی |
| browser smoke | باز | تست لاگین‌شده روی artifact نهایی |

فرمان بررسی:

```powershell
python scripts/verify_operator_gates.py path\to\operator-gates.production.json
```

---

## 6. ماتریس پذیرش کارفرما

| حوزه | مدرک | مسئول تأیید |
| --- | --- | --- |
| قابلیت‌ها | سناریوهای پذیرش و ویدئو/تصویر | کارفرما + QA |
| قیمت‌ها | provider matrix و نمونه live | Product + Pricing |
| امنیت | scan، rotation و access review | Security/Ops |
| حریم خصوصی | متن نهایی و consent receipts | مالک + مشاور حقوقی |
| دسترسی‌پذیری | keyboard/screen-reader/zoom report | QA |
| بازیابی | restore report و RTO/RPO | Ops |
| عملیات | monitoring، alert و runbook | Ops |
| کد | CI سبز، tag و checksum | Engineering |
| مالکیت | حساب‌ها و دسترسی‌های کارفرما | کارفرما |

---

## 7. ترتیب پیشنهادی و زمان

| بازه | کار اصلی | نتیجه |
| --- | --- | --- |
| روز ۱ تا ۳ | فاز 0 | CI سبز و baseline قابل اعتماد |
| هفته ۱ | فاز 1 و شروع فاز 2 | تصمیم داده/حقوق و rotation |
| هفته ۲ | پایان فاز 2 | staging، restore، monitoring و edge پایدار |
| هفته ۳ | فاز 3 | پذیرش کامل و soak 24h |
| پایان هفته ۳ | فاز 4 | بسته تحویل قابل بازسازی |
| هفته ۴ | فاز 5 | انتشار، امضا و hypercare |

**برآورد تحویل امن:** حدود ۳ تا ۴ هفته، اگر پاسخ حقوقی/provider معطل نشود.  
**برآورد بلوغ ۱۰/۱۰:** ۳ تا ۴ هفته دیگر برای soak 72h، refactor مشترک
web/desktop، تست بار سنگین، staging دائمی، canary deploy و بازبینی امنیتی مستقل.

---

## 8. کارهای P1 پس از تحویل اولیه

- استخراج لایه مشترک web/desktop و حذف drift.
- پوشش E2E برای support، admin mutation و همه کانال‌های delivery.
- تست ۱۰هزار هشدار و سقف WebSocket.
- blue/green یا canary deploy با rollback خودکار.
- SLO رسمی برای availability، freshness و alert latency.
- ممیزی امنیتی شخص ثالث.
- بررسی dependency/license دوره‌ای و SBOM در هر release.

## 9. کارهای P2

- API key و quota برای مصرف‌کننده ثالث، فقط در صورت عرضه عمومی API.
- relay چندمنطقه‌ای.
- billing/subscription پس از طراحی محصول، پرداخت، refund و بازبینی حقوقی تازه.
- بازار جهانی پس از تصمیم data transfer، مالیات، تحریم و متن حقوقی تازه.

---

## 10. شرایط توقف فوری تحویل

در هرکدام از موارد زیر go-live متوقف شود:

- CI قرمز یا artifact متفاوت از staging.
- restore ناموفق یا backup بدون کلید قابل بازیابی.
- credential قدیمی هنوز معتبر.
- login، session، consent یا admin permission خراب.
- قیمت بدون منبع/واحد/timestamp یا داده stale با ظاهر live.
- migration drift یا rollback نامشخص.
- health قرمز، dead-letter رو به رشد یا monitoring خاموش.
- متن حقوقی با رفتار واقعی سیستم ناسازگار.
- نبود تأیید کارفرما برای limitationهای قیمت.

---

## 11. منبع حقیقت

- وضعیت فنی و تاریخچه: [`PROJECT_STATUS.md`](../PROJECT_STATUS.md)
- backlog: [`FUTURE_TASKS.md`](../FUTURE_TASKS.md)
- عملیات انتشار: [`release-operations.md`](release-operations.md)
- وضعیت حقوقی: [`legal-readiness-2026-09-19.md`](legal-readiness-2026-09-19.md)
- عملیات قیمت: [`pricing-operations-runbook.md`](pricing-operations-runbook.md)
- بازیابی Redis: [`redis-recovery.md`](redis-recovery.md)
- زمان سرور: [`time-sync-runbook.md`](time-sync-runbook.md)
- providerها: [`api-providers-reference.md`](api-providers-reference.md)

اگر این سند با یک گزارش قدیمی تناقض داشت، اول وضعیت live و CI دوباره بررسی
شود، سپس هر دو سند در همان commit اصلاح شوند. ادعای تحویل فقط با مدرک تازه معتبر است.
