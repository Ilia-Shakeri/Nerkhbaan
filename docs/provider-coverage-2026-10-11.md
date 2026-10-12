# پوشش منابع — ۲۰۲۶-۱۰-۱۲

نسخهٔ کد: 2.8.1، commit ‏`ad94dc0e87d771044175701b4259aa97091aee3a`؛ تصویر زنده `770194731dee…`. زمان‌ها: UTC. جدول منابع، آزمون تازهٔ ۲۰۲۶-۱۰-۱۲ است؛ شاهدهای روز قبل با تاریخ جدا آمده‌اند. نتیجهٔ محلی، نتیجهٔ استقرار نیست.

- [پوشش]: ۳۹ مسیر برای ۱۱ دارایی. ۲۳ مسیر روشن؛ ۲۲ مسیر دارای تنظیم. آزمون تازهٔ سرور در ۲۰۲۶-۱۰-۱۲ 07:38:32 تا 07:38:58: یازده parser موفق، یازده شکست، هفده مسیر ردِ آزمون. یکی از موفق‌ها، Bitpin USDT، خارج پنجرهٔ زنده بود. این اعداد، پوشش کاملِ زنده نیست.
- [سیاست]: مسیر خاموش، خاموش ماند. کلید به میزبان دیگر نرفت. واحد مبهم، زمان کهنه و منبع نامستقل، مجوز تأیید نگرفت.
- [حقوق]: موفقیت HTTP، حق تجاری ثابت نمی‌کند. محدودیت و انتساب هر فروشنده جدا باید رعایت شود.

## ماتریس همهٔ مسیرها

نتیجهٔ تازه از `provider-coverage-final-2026-10-12.json`. حداکثر یک GET برای هر مسیر روشن و دارای تنظیم؛ aggregate مشترک یک بار دریافت شد. history در این نوبت درخواست نشد. هر دو API همان تصویر نهایی داشتند؛ شناسه و StartedAt پیش و پس برابر بود. DB/Redis نوشته نشد. «موفق» یعنی parser قرارداد را پذیرفت؛ شرط زنده جدا است. رسید قبلی `provider-coverage-target.json` مربوط به ۲۰۲۶-۱۰-۱۱ است.

| دارایی | مسیر | نقش مؤثر هنگام آزمون | نتیجه |
|---|---|---|---|
| GOLD_18K_TOMAN_GRAM | wallgold_gold18 | primary | موفق؛ گرم، تومان، عیار ۰٫۷۵؛ زمان دریافت |
| GOLD_18K_TOMAN_GRAM | alanchand_gold18 | primary | روشن؛ کلید ندارد |
| GOLD_18K_TOMAN_GRAM | tala_gold18_toman | verifier | خاموش؛ کلید ندارد |
| GOLD_24K_TOMAN_GRAM | tala_gold24_toman | primary | خاموش؛ کلید ندارد |
| GOLD_24K_TOMAN_GRAM | persian_toolbox_gold24 | fallback | خاموش؛ مسیر معتبر ثبت نیست |
| GOLD_24K_TOMAN_GRAM | nerkh_io_gold24 | fallback | خاموش؛ کلید ندارد |
| XAU_USD_OZ | goldapi_xau | primary | ConnectTimeout |
| XAU_USD_OZ | gold_api_free_xau | fallback | ConnectError؛ مسیر مستقیم سرور؛ فید جدا سنجیده شود |
| XAU_USD_OZ | metals_dev_gold | fallback | ConnectTimeout |
| SILVER_999_TOMAN_GRAM | tala_silver999_toman | primary | خاموش؛ کلید ندارد |
| SILVER_925_TOMAN_GRAM | wallgold_silver925 | primary | موفق؛ گرم، تومان، عیار ۰٫۹۲۵؛ زمان دریافت |
| XAG_USD_OZ | goldapi_xag | primary | ConnectTimeout |
| XAG_USD_OZ | gold_api_free_xag | fallback | ConnectError |
| XAG_USD_OZ | xaus_xag | fallback | خاموش؛ تنظیم دارد |
| XAG_USD_OZ | metals_dev_silver | fallback | ConnectTimeout |
| USD_TOMAN | navasan_usd_toman | primary | خاموش؛ کلید ندارد |
| USD_TOMAN | servix_usd_toman | fallback | خاموش؛ تنظیم دارد |
| USD_TOMAN | persian_toolbox_usd_toman | fallback | خاموش؛ تنظیم دارد |
| USDT_TOMAN | nobitex_stats_usdt | primary | موفق؛ زمان دریافت؛ تومان |
| USDT_TOMAN | nobitex_orderbook_usdt | verifier | موفق؛ زمان منبع؛ تومان |
| USDT_TOMAN | bitpin_usdt_toman | fallback | parser موفق؛ سن ۵۴٫۷۱۶ ثانیه، مهلت زنده ۲۰ ثانیه؛ زنده نیست |
| USDT_TOMAN | tetherland_usdt | fallback | موفق؛ زمان دریافت؛ تومان |
| USDT_TOMAN | wallex_usdt_toman | fallback | موفق؛ زمان دریافت؛ تومان |
| USDT_TOMAN | tala_usdt_toman | fallback | خاموش؛ کلید ندارد |
| USDT_TOMAN | navasan_usdt | fallback | خاموش؛ کلید ندارد |
| USDT_USD | coinbase_usdt_usd | primary | ConnectTimeout |
| USDT_USD | coingecko_usdt | fallback | ConnectTimeout |
| USDT_USD | servix_usdt_usd | fallback | خاموش؛ تنظیم دارد |
| USDT_USD | coincap_usdt | fallback | خاموش؛ تنظیم دارد |
| BTC_TOMAN | nobitex_stats_btc | primary | موفق؛ زمان دریافت؛ تومان |
| BTC_TOMAN | nobitex_orderbook_btc | verifier | موفق؛ زمان منبع؛ تومان |
| BTC_TOMAN | bitpin_btc_toman | fallback | stale_timestamp؛ قیمت رد شد |
| BTC_TOMAN | tetherland_btc | fallback | خاموش؛ تنظیم دارد |
| BTC_TOMAN | wallex_btc_toman | fallback | موفق؛ زمان دریافت؛ تومان |
| BTC_USD | coinbase_btc_usd | primary | ConnectTimeout |
| BTC_USD | coingecko_btc | fallback | ConnectTimeout |
| BTC_USD | persian_toolbox_btc | fallback | موفق؛ سن منبع ۷۲٫۰۰۱ ثانیه؛ پنجرهٔ زنده باز |
| BTC_USD | servix_btc_usd | fallback | خاموش؛ تنظیم دارد |
| BTC_USD | coincap_btc | fallback | خاموش؛ تنظیم دارد |

## محصول زنده، ۲۰۲۶-۱۰-۱۲ 07:39:04

این خواندنِ پالودهٔ واقعی همان تصویر زنده، پس از آزمون مستقیم و پیش از dispatch تازهٔ فید بود؛ خروجی HTTPS جدا توسط آزمون استقرار سنجیده شد. هر وضعیت فقط همین لحظه را می‌گوید.

| دارایی | منبع محصول | نتیجهٔ همان لحظه |
|---|---|---|
| GOLD_18K_TOMAN_GRAM | wallgold_gold18 | live؛ ذخیره‌شده؛ مهلت زنده باز |
| GOLD_24K_TOMAN_GRAM | ندارد | unavailable؛ منبع مستقیم معتبر کم |
| XAU_USD_OZ | gold_api_free_xau | stale؛ منبع 06:39:39، مهلت زنده 06:49:00 گذشته |
| SILVER_999_TOMAN_GRAM | derived:silver_999_toman_gram | expired؛ محاسبه‌شده، مستقیم نیست |
| SILVER_925_TOMAN_GRAM | wallgold_silver925 | live؛ ذخیره‌شده؛ مهلت زنده باز |
| XAG_USD_OZ | gold_api_free_xag | stale؛ منبع 06:39:39، مهلت زنده 06:45:57 گذشته |
| USD_TOMAN | derived:usd_toman | expired؛ محاسبه‌شده، دلار نقدی مستقیم نیست |
| USDT_TOMAN | nobitex_stats_usdt | fresh_cache؛ valid_until ‏07:38:59 گذشته |
| USDT_USD | coingecko_usdt | expired؛ منبع 06:39:38؛ فید پیوسته نیست |
| BTC_TOMAN | nobitex_stats_btc | live؛ ذخیره‌شده؛ مهلت زنده باز |
| BTC_USD | persian_toolbox_btc | live؛ ذخیره‌شده؛ زمان منبع 07:37:46 |

- [تأیید مستقل تازه]: همان canary برای USDT، Nobitex/Tetherland/Wallex اختلاف ۰٫۰۴۵۴٪ و ۰٫۰۰۳۰٪ با پنجرهٔ زندهٔ مشترک داشت؛ BTC، Nobitex/Wallex ‏۰٫۲۳۶۴٪. stats و orderbook یک خانواده‌اند؛ Bitpin USDT پنجرهٔ مشترک زنده نداشت. این فقط مقایسهٔ خواندنی است؛ رأی یا quote تولید ثبت نشد.

## شاهد تاریخی محصول، ۲۰۲۶-۱۰-۱۱ پیش از استقرار 2.8.1

رسید `provider-public-snapshot.json` در 12:58:53، خروجی پالودهٔ واقعی سرویس است؛ قیمت کهنهٔ قرنطینه‌شده را به محصول برنمی‌گرداند.

| دارایی | منبع محصول | نتیجهٔ همان لحظه |
|---|---|---|
| GOLD_18K_TOMAN_GRAM | wallgold_gold18 | live؛ ذخیره‌شده |
| GOLD_24K_TOMAN_GRAM | ندارد | unavailable؛ فرمول طلا ممنوع |
| XAU_USD_OZ | ندارد | unavailable؛ مسیر واسط جدید هنوز منتشر و فعال نشده |
| SILVER_999_TOMAN_GRAM | derived:silver_999_toman_gram | stale؛ فرمول نقره، قیمت مستقیم نیست |
| SILVER_925_TOMAN_GRAM | wallgold_silver925 | fresh_cache؛ valid_until گذشته |
| XAG_USD_OZ | gold_api_free_xag | fresh_cache؛ valid_until گذشته |
| USD_TOMAN | derived:usd_toman | stale؛ نسبت بازار تتر، دلار نقدی مستقیم نیست |
| USDT_TOMAN | nobitex_stats_usdt | fresh_cache؛ valid_until گذشته |
| USDT_USD | coingecko_usdt | fresh_cache؛ valid_until گذشته |
| BTC_TOMAN | nobitex_stats_btc | fresh_cache؛ valid_until گذشته |
| BTC_USD | persian_toolbox_btc | fresh_cache؛ valid_until گذشته |

- [تازگی]: `fresh_cache` می‌تواند پس از `valid_until` باشد. برای اعلان عادی، مهلت زنده و ذخیرهٔ قطعی هم لازم است. برچسب کش، شاهد زنده نیست.
- [زمان]: Wallgold و برخی پاسخ‌های تجمیعی، زمان جدا ندارند. دریافت HTTP صریح ثبت شد؛ زمان بازار ادعا نشد.
- [استقلال]: Nobitex stats و orderbook یک خانواده‌اند. Wallex و Wallgold هم خانواده‌اند. تأیید مستقل از این جفت‌ها درنمی‌آید.
- [مقایسه]: هنگام آزمون، Nobitex/Tetherland/Wallex برای USDT در بازهٔ زنده هم‌پوشان بودند؛ اختلاف حدود ۰٫۰۷۵۷٪ و ۰٫۰۷۳۳٪. Nobitex/Wallex برای BTC حدود ۰٫۴۲۴۲٪. این مقایسه فقط خواندنی بود؛ رأی تأیید در پایگاه ثبت نشد.

## مسیر بیرونی و XAU

- [دسترسی]: آزمون بدون کلید روی Windows در 12:46:19، پنج GET موفق داشت: XAU، XAG، CoinGecko و دو Coinbase. همان منابع روی سرور ایران خطای اتصال داشتند. قطع همان میزبان ثابت شد؛ تعطیلی همهٔ فروشنده‌ها ثابت نشد.
- [یکشنبه]: منبع XAU/XAG زمان `updatedAt` همان روز داشت. این، زمان به‌روزرسانی فروشنده است؛ باز بودن بورس جهانی ثابت نمی‌کند.
- [قرارداد XAU]: [صفحهٔ رسمی طلا](https://gold-api.com/assets/gold) مسیر `/price/XAU`، نماد XAU، USD و `updatedAt` دارد. [صفحهٔ اصلی](https://gold-api.com/) واحد USD per Oz را بیان می‌کند. کد فقط `XAU_USD_OZ` می‌گیرد؛ گرم و عیار داخلی از آن ساخته نمی‌شود.
- [استفاده]: [شرایط رسمی](https://gold-api.com/terms)، نسخهٔ مؤثر ۲۰۲۶-۰۹-۱۰، استفاده در برنامه‌های تجاری و سایت مشتری را مجاز می‌داند. این گزارش، مجوز فروش دوبارهٔ داده یا تأیید حقوقی قرارداد خصوصی نیست.
- [نقش]: `gold_api_free_xau` به fallback با priority دو رفت؛ تغییر همان نقش با audit شمارهٔ هفت، حالت قبل و حفظ بودجه و مهلت ثبت شد. override ذخیره‌شدهٔ disabled همچنان محترم است. جفت غلط، تاریخچهٔ بی‌پشتیبان، زمان غلط، جهش بی‌تأیید و ورودی نامستقل همچنان رد می‌شود.
- [فید]: نسخهٔ ۱، همان سه دارایی لازم را دارد. نسخهٔ ۲، یک تا چهار دارایی معتبر دارد. شکست یک منبع، دیگرها را قطع نمی‌کند. هیچ منبع سالم نباشد، فید قبلی حفظ می‌شود. زمان نشر، جای زمان مشاهده ننشست.
- [فید محلی]: `provider-feed-local-proof.json` در 13:09:29: سه HTTP واقعی موفق؛ چهار quote نسخهٔ ۲، بدون حذف. سن مشاهدهٔ XAU/XAG حدود ۲۲–۲۴ ثانیه؛ BTC/USDT حدود ۷۹ ثانیه. نشر و ingest سرور با این آزمون ثابت نشد.
- [تداوم]: [اجرای دستی 38140715926](https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/38140715926) در 12:49:19 موفق شد و سه مسیر قدیم را موقت برگرداند. cron پنج‌دقیقه‌ای، اجراهای واقعی با فاصلهٔ چند ساعت داشت. یک اجرا، پوشش دائمی ثابت نمی‌کند. میزبان بیرونیِ پیوسته با فاصلهٔ ثابت و پایش سن فید هنوز لازم است.
- [پذیرش واقعی چهار مسیر]: [اجرای 38145677275](https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/38145677275) در ۲۰۲۶-۱۰-۱۱ 14:04:16 موفق شد؛ نسخهٔ دو با چهار quote و حذف صفر. consumer ابتدا 14:04:45 پاسخ 503 داشت؛ تلاش عادی بعد در 14:05:47، 202 گرفت. علت ریز 503 در log نبود؛ ادعا نشد. هیچ lock یا بودجه پاک نشد. چهار provider quote پذیرفته و چهار canonical مرتبط واقعاً در PostgreSQL یافت شد: BTC ‏522113→326750، USDT ‏522123→326757، XAG ‏522112→326749 و XAU ‏522124→326758. قیمت و زمان مشاهده با منبع برابر بود؛ رسید فقط boolean برابری دارد، قیمت خام ندارد.
- [XAU تحویل]: منبع 14:04:07، دریافت و canonical ‏14:05:47.219755؛ USD/troy_ounce، عیار 0.9999، reference_rate، derived=false. خروجی HTTPS واقعی همان canonical و زمان را داشت. مهلت زنده 14:10:47.219755؛ خواندن 14:15:58، `fresh_cache` داشت. این شاهد تحویل واقعی همان نوبت است؛ پوشش پیوستهٔ روز بعد نیست. رسید `provider-live-persistence-proof.json` و `provider-final-relay-metadata.json`.

## تاریخچه

- [Nobitex]: [سند رسمی OHLC](https://apidocs.nobitex.ir/market_data/%D8%AF%D8%B1%DB%8C%D8%A7%D9%81%D8%AA-%D8%AF%D8%A7%D8%AF%D9%87-%D9%87%D8%A7%DB%8C-ohlc) سقف ۵۰۰ کندل و پارامتر `page` دارد. کد قبلی، ماه را پس از یک صفحه ناقص می‌گرفت. کد جدید، صفحه‌ها را با بودجه و lease می‌گیرد؛ زمان تکراریِ متعارض یا صفحهٔ بی‌پیشرفت، رد می‌شود.
- [ماه BTC]: `provider-pagination-after.json` در 12:59:26: ۷۲۰ نقطه، دو درخواست واقعی؛ زمان یکتا و مرتب؛ فقط historical. شمارش callback ذخیره ۷۲۰+۷۲۰ بود. این اجرا، هیچ DB/Redis ننوشت؛ شاهد ذخیرهٔ واقعی نیست.
- [ذخیرهٔ ماه]: `provider-stage-durable-proof.json` در 13:23:42 تا 13:24:27، روی کپی جدا و API `2.8.1-7402757` سبز شد. دو پاسخ واقعی Windows با hash ثابت، در transport کپی بازپخش شد؛ شبکهٔ کپی بسته بود. مسیر واقعی `PricingPersistence`، ۷۲۰ ردیف provider و ۷۲۰ canonical در PostgreSQL نوشت. زمان‌ها همان منبع، از ۲۰۲۶-۰۹-۱۱ 13:30 تا ۲۰۲۶-۱۰-۱۱ 12:30؛ پیوند منبع، ترتیب، یکتایی و historical بررسی شد. این، نوشتن واقعی روی کپی است؛ ingest تولید با آن ثابت نمی‌شود.
- [حفظ کپی]: نام و نشان مالک پایگاه و hash کد پیش از نوشتن چک شد. instrument/provider/job تست، شناسهٔ یکتا و کاتالوگ خاموش داشت. پس از پاک‌سازی دقیق همان مالک: ۱۱ instrument، ۳۹ provider، ۱۳۳۵۸ job، ۵۲۰۴۴۴ provider quote، ۳۲۵۴۸۶ canonical quote، چهار کاربر و digest همان کاربران حفظ شد. DB/Redis تولید و سرویس‌های دیگر دست نخورد.
- [USDT تاریخچه]: بازهٔ ۲۴، ۷۲ و ۷۲۰ ساعت، `HTTP 200 / s=no_data` داشت. parser آن را صفر نقطه می‌داند؛ نه خرابی شبکه، نه تاریخچهٔ ساختگی. صفر نقطه، پوشش تاریخی کامل نیست.
- [job خالی]: صفر نقطه، `deferred / provider_returned_no_history` دارد؛ completed نمی‌شود. بازه و زمان تلاش بعدی حفظ می‌شود.
- [بودجه]: کمبود سهم صفحهٔ بعد، job را deferred می‌کند؛ نوشتهٔ ناقص ندارد. range اصلی حفظ می‌شود. lease گم شود، صفحهٔ بعد و commit نمی‌رود.
- [XAU/XAG]: این مسیر عمومی، تاریخچهٔ تأییدشده ندارد. [طرح رسمی](https://gold-api.com/pricing) کلید و محدودیت تاریخچه را جدا دارد. تاریخچه از قیمت امروز ساخته نمی‌شود.

## رفع‌ها و تست

- [تازگی خواندن]: canonical هنگام پذیرش واسط، پنجرهٔ کوتاهِ دریافت داشت؛ خواندن بعدی آن را به زمان منبع برمی‌گرداند و دو دقیقه کم می‌کرد. anchor و سقف منبع حالا ذخیره می‌شود. سیاست جدید فقط مهلت را کم می‌کند؛ هیچ خواندن، مهلت قبلی یا سقف سن منبع را زیاد نمی‌کند. دادهٔ قدیم یا metadata غلط، همان anchor مشاهده دارد.
- [WebSocket]: اتصال اولیه و resync، برای هر مشتری دوباره snapshot می‌خواند. اجرای شمارشیِ همان مسیر کد برای ۲۰۰ خواندن و ۹ دارایی، ۹۲۰۰ فراخوانی SQL داشت. hub جدید، فقط خواندنِ هنوز تمام‌نشده را مشترک می‌کند. پیش از خواندن گروهی، یک reader و ۴۶ فراخوانی داشت؛ پس از آن، یک reader و سه فراخوانی. کش زمانی ندارد؛ read بعدی سیاست روز را می‌خواند. لغو یک مشتری، read بقیه را نمی‌کشد؛ خطای مشترک پاک می‌شود و تلاش بعدی ممکن است. رسیدهای `ws-snapshot-query-review-before-bulk.json` و `ws-snapshot-query-review-after-bulk.json` شمارش adapter هستند؛ سنجش latency پایگاه واقعی نیست. burst سرد واقعی تصویر `a081a723…` با ۲۰۰ اتصال هم‌زمان، همان بودجهٔ ۱۲/۲۰ ثانیه و صفر خطا، p95 ‏1.347 ثانیه و بیشینهٔ 1.383 ثانیه داشت؛ شکست قدیم حفظ شد.
- [خواندن گروهی]: هر snapshot قبلی، برای ۹ دارایی ۴۵ SELECT قانون داشت. اکنون یک SELECT دارایی و یک SELECT قانون سراسری/دارایی دارد؛ SELECT قیمت قطعی حفظ شد. فهرست دارایی هم همان قانونِ همان درخواست را استفاده می‌کند. مقدار تهی یا خرابِ scoped، همان‌طور که پیش‌تر بود، مقدار global را می‌پوشاند. قانون خاموشی، عیار، قیمت مجاز و مرز تازگی حفظ شد. تغییر ادمین در درخواست بعدی خوانده می‌شود؛ کش کامل یا مهلت تازه ساخته نشد. آزمون SQLite واقعی، دو SELECT و برابری خواندن گروهی و تک‌دارایی را سنجید.
- [schema فید]: schema دارایی و provider، XAU را نداشت؛ batch چهارقیمتی روی سرور `HTTP 422` داشت. هر دو allowlist دقیق اصلاح شد. سه تست مسیر HTTP با HMAC واقعیِ کلید تست: چهار quote پذیرفته؛ جفت طلای ۲۴ یا provider ناشناس، پیش از ingest رد می‌شود. زمان و امضای تولید در تست استفاده نشد. تصویر `a081a723…` سپس چهار مسیر واقعی را با پیوند ذخیرهٔ منبع و canonical پذیرفت؛ شاهد بالا.
- [پایگاه تست]: fixture تاریخچه از یک اتصال SQLite در دو thread استفاده می‌کرد. native یک خطای RowMapping داشت؛ بازآزمایی ۲۰ دور، ۱۳۵ تداخل cursor و دو شکست ثبت کرد. fixture تاریخچه و خواندن گروهی، فایل موقت یکتا و QueuePool گرفتند؛ هر thread اتصال جدا دارد. catch تولید برای پنهان‌کردن خطا اضافه نشد. روی تصویر تازه `a081a723…`، همان آزمون ۲۰/۲۰ سبز؛ تداخل cursor روی همان اتصال صفر. رسید قبل و بعد حفظ شد.
- [کد پیشین]: ۱۳۳ تست هدفمند Python سبز؛ چهار تست خواندن تازگی، پنج تست snapshot هم‌زمان، هفت تست خواندن گروهی و SQL، هشت تست نوبت تاریخچه، سه تست HTTP فید، صفحه‌بندی، قرارداد XAU، نقش و خاموشی، استقلال و فید جزئی. هشت تست Go سبز با `golang:1.26.9-alpine3.24`. این‌ها تست همان کد پیش از رفع بارند؛ با تعداد مجموعهٔ کامل یکی نیستند.
- [مجموعهٔ کامل تازه]: پس از رفع صف و کش قیمت، در ۲۰۲۶-۱۰-۱۲، ۳۸۴ تست محلی اجرا شد: ۳۷۴ پاس، ده skip و شکست صفر. این نتیجهٔ محلی است؛ چهار تست PostgreSQL واقعیِ تصویر جدا پاس شد. `pyflakes` روی یازده فایل تغییرکرده پاک است.
- [تصویر پیشین]: تصویر API با شناسهٔ `a081a7239bedd090d8cecae085476b8164522ec446c814ae116191d39719fb32`، در ۲۰۲۶-۱۰-۱۱، ۱۵۲ تست native با skip صفر و چهار تست PostgreSQL واقعی گذراند. ingest چهارمنبع و نتیجهٔ رد بار همان تصویر جدا ثبت شد.
- [تصویر رفع بار]: تصویر تازهٔ `770194731dee57a2b6d1b566073393471d8adda14d11011a4692abc8f864b17e` در ۲۰۲۶-۱۰-۱۲، ۱۷۳ تست native با skip صفر، چهار تست PostgreSQL 17.11 واقعی با پاک‌سازی fixture، ۲۰/۲۰ تکرار fixture با صفر تداخل همان اتصال و Trivy 0.70 با HIGH صفر و CRITICAL صفر گذراند. hash تمام ۱۰۹ فایل frozen و workspace برابر بود. تصویر دقیق روی میزبان هدف بارگذاری شد؛ در این مرحله هیچ container، commit یا deployment عوض نشد. قبولی بار و قیمت جاری روی این تصویر، مدرک بعدی لازم دارد.
- [بار HTTP]: تصویر `a081a723…` در آزمون ۶۰ثانیه، هدف ۱۵ درخواست/ثانیه را نگرفت: ۴۹۶ پاسخ 200 در 62.286 ثانیه، 7.963 درخواست/ثانیه؛ p95 ‏6199.772ms. مسیر BTC تاریخچه ۶۴ SELECT و gold ‏۴۴ SELECT داشت؛ fanout قانون و enqueue تکراری علت‌های تأییدشده بودند. کپی تست، ۴۱۷۴ کار pending تازه ساخت؛ دقیق همان ردیف‌ها پاک شدند و ۱۳۳۵۸ ردیف اولیه با fingerprint کامل حفظ شد. تولید پاک نشد.
- [صف خودکار تازه]: درخواست‌های تاریخچه، range با microsecond تازه داشتند؛ هر GET یک job تازه می‌ساخت. اکنون guard اتمیِ مالک‌دار Redis، instrument و bucket بازه را برای ۶۰ ثانیه مشترک می‌کند. range ذخیره همان زمان واقعی است؛ cursor و کار قدیم عوض نمی‌شود. مجوز دارایی و feature در هر درخواست تازه خوانده می‌شود؛ coalesced با پنج SELECT واقعی، scoped-disabled با سه SELECT. provider فقط هنگام ساخت خوانده می‌شود؛ policy همهٔ providerها دو SELECT دارد. مسیر بدون قرارداد تاریخچه، زود رد می‌شود. Redis قطع باشد، خودکار deferred است؛ صف بی‌قفل نمی‌سازد. شکست یا لغو، فقط guard همان مالک را آزاد می‌کند. enqueue دستی و retry آن، همان مسیر قبلی است. سقف، تقریباً یک job برای هر دارایی و bucket-gap در هر دقیقه است؛ تغییر bucket یا شکاف تازه، کلید تازه دارد. این قفل، کش قیمت یا ادعای پوشش تاریخچه نیست.
- [کش قیمت]: payload کامل قبلاً پنج ثانیه در حافظه و ده ثانیه با header عمومی نگه داشته می‌شد؛ انقضای نرخ و خاموشی ادمین دیر دیده می‌شد. اکنون فقط خواندن هنوز تمام‌نشده شریک است؛ هشت تاریخچهٔ کوتاه Redis پیش از خواندن قیمت و مجوز جاری تمام می‌شوند. سپس status و deadline هنگام تحویل هر caller سنجیده می‌شود. درخواست بعد از اتمام، دوباره سیاست را می‌خواند. HTTP جاری `Cache-Control: no-store` دارد؛ لغو یک caller خواندن بقیه را قطع نمی‌کند، شکست مشترک تلاش بعدی را مسدود نمی‌کند. این تغییر هیچ `valid_until` را زیاد نمی‌کند.
- [تست رفع بار]: ۲۱ تست تازه: هشت guard با ۲۰۰ درخواست هم‌زمان و یک range ذخیره‌شده، چهار policy گروهی با SQL واقعی، یک شمارش مجوز تازه و هشت تست قیمت/HTTP. این هشت، انقضا زیر مهلت کش قدیم، انقضا وسط تاریخچه، خاموشی فوری و خاموشی وسط انتظار با caller جدید، نرخ جدید، ۲۰۰ خواندن با یک snapshot و هشت Redis، لغو/شکست/retry و header واقعی را سنجیدند. مجموعهٔ هدفمند تازه، ۱۳۷ تست با skip صفر و pyflakes پاک روی یازده فایل دارد؛ تعداد این زیرمجموعه با مجموعهٔ قبلی ۱۳۳ یکی نیست. تصویر native تازه، ۱۷۳ تست و چهار PostgreSQL واقعی پاس دارد؛ بار واقعی تازه هنوز باید سنجیده شود. SQL تاریخچه تغییر نکرد؛ `first/last` روی Timescale سریع‌تر بود، ولی PostgreSQL معمولی هم باید پشتیبانی شود؛ این تغییر فعلاً اعمال نشد.
- [بازبینی]: امتیاز تحویل این بخش ۸/۱۰ تا تصویر تازه آزمون بار را بگذراند. پوشش کامل منبع هم کلید، منبع ۲۴ عیار و تداوم مسیر بیرونی می‌خواهد. عدد بهتر بدون مدرک داده نشد.

## ورودی لازم برای گره‌های باز

| گره | ورودی یا کار لازم | مدرک پذیرش |
|---|---|---|
| GOLD_24K_TOMAN_GRAM | منبع مستقیم معتبر با کلید، حق استفاده، واحد گرم، تومان/ریال، عیار و زمان منبع | payload واقعی پالوده، قرارداد رسمی، تبدیل واحد یک‌باره، ذخیرهٔ قطعی و خروجی زنده |
| alanchand_gold18 | توکن در secret store سرور؛ قرارداد و حق استفادهٔ فعلی | canary همان مسیر، بدون نشر کلید |
| بین‌المللی روی سرور ایران | مسیر خروجی یا میزبان بیرونی آماده، TLS معتبر، محدودیت درخواست و پایش | چند اجرای خودکار پیوسته، زمان مشاهدهٔ حفظ‌شده، ingest و canonical ذخیره‌شده |
| تداوم فید 2.8.1 | publisher و consumer منتشر؛ چهار مسیر و XAU ذخیره‌شده ثابت؛ اکنون اجرای خودکارِ پیوسته لازم | چند اجرای خودکار تازه، سن واقعی منبع و پیوند ذخیره؛ یک اجرای دستی کافی نیست |
| USDT history no_data | مسیر تاریخی دیگر با قرارداد/حق معتبر، یا اعلام صریح عدم پوشش | تاریخچهٔ واقعی در بازهٔ درخواست؛ صفر ساختگی نباشد |
| منابع خاموش دارای کلید | بازبینی حق استفاده و قرارداد همان route؛ سپس تصمیم فعال‌سازی | canary جدا و audit نقش؛ وجود کلید، اجازهٔ فعال‌سازی نیست |

- [نامزد ۲۴]: [فهرست رسمی Servix](https://servix.cc/supported-assets) دارایی `GOLD_24_RLS` را نشان می‌دهد. هنوز مسیر ۲۴ در این پروژه ثبت و آزمون نشده. قرارداد پاسخ، عیار، زمان، حق استفاده و نمونهٔ واقعی لازم؛ خودکار فعال نشد.
- [منابع رسمی]: [Coinbase ticker](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-ticker) زمان آخرین tick را دارد. [CoinGecko simple price](https://docs.coingecko.com/reference/simple-price) با `include_last_updated_at=true` زمان مشاهده می‌دهد. این زمان‌ها عوض نمی‌شوند؛ انتساب فروشنده محفوظ است.

## تکرار آزمون خواندنی

از `apps/api`، با تنظیمات خصوصی همان محیط:

```bash
python scripts/probe_provider_coverage.py --execute-network --history --output /secure-evidence/provider-coverage.json
```

- [خروجی]: `0` فقط نبودِ خطای مسیر روشن و دارای تنظیم را می‌گوید. `value_proof.live_at_receive`، مسیر بی‌کلید، history و استقلال هم باید خوانده شود؛ خروج صفر، پوشش همهٔ دارایی‌ها نیست.
- [رسید]: فایل‌ها در بستهٔ بیرون از Git، `Nerkhbaan-Delivery/remaining-20261011/` هستند. `provider-proof-manifest.json` نام، زمان و SHA-256 دارد. هیچ کلید یا payload مشتری داخل رسید نیست.
