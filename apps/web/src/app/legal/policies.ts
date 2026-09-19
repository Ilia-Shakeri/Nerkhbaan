export const POLICY_VERSION = '2026-09-19.1';
export const OPERATOR_EMAIL = 'iliashkr@gmail.com';
export type PolicyKind = 'privacy' | 'terms' | 'cookies' | 'refunds' | 'business';
type Text = { fa: string; en: string };
export const policyTitles: Record<PolicyKind, Text> = {
  privacy: { fa: 'حریم خصوصی', en: 'Privacy policy' },
  terms: { fa: 'شرایط استفاده', en: 'Terms and conditions' },
  cookies: { fa: 'کوکی و ذخیره‌سازی', en: 'Cookie policy' },
  refunds: { fa: 'لغو و بازپرداخت', en: 'Cancellation and refunds' },
  business: { fa: 'اطلاعات کسب‌وکار', en: 'Business details' },
};
export const policies: Record<PolicyKind, { title: Text; body: Text }[]> = {
  privacy: [
    { title: { fa: 'مسئول و راه تماس', en: 'Operator and contact' }, body: {
      fa: 'مسئول نرخ‌بان ایلیا شاکری (Ilia Shakeri)، مستقر در تهران، ایران است. برای حریم خصوصی، درخواست‌های داده و پشتیبانی به iliashkr@gmail.com ایمیل بزنید؛ داشتن حساب لازم نیست. نشانی عمومی پستی فعلاً ارائه نشده است. خدمت فعلاً رایگان و بازار هدف فعلی ایران است.',
      en: 'Nerkhbaan is operated by Ilia Shakeri (ایلیا شاکری), based in Tehran, Iran. Email iliashkr@gmail.com for privacy, data requests and support; no account is required. No public postal address is currently provided. The service is currently free and its present target market is Iran.' } },
    { title: { fa: 'خدمات اختیاری', en: 'Optional services' }, body: {
      fa: 'برای اعلان پیامک یا تلگرام، فقط در صورت انتخاب آن خدمت شماره یا شناسه مقصد دریافت می‌شود. متن و تاریخچه گفتگو در دستیار هوشمند ذخیره و برای پاسخ به ارائه‌دهنده پردازش و مسیرهای جایگزین پیکربندی‌شده ارسال می‌شود؛ ممکن است پردازش خارج کشور باشد. اطلاعات شخصی یا محرمانه در گفتگو نفرستید. گفتگو را می‌توانید حذف کنید؛ پاک‌سازی خودکار برای گفتگوهای بدون فعالیت بیش از ۳۱ روز طراحی شده است، نه ۳۱ روز پس از هر پیام. نسخه‌های پشتیبان و سیاست ارائه‌دهنده جدا هستند.',
      en: 'SMS or Telegram destinations are collected only if you choose those services. Smart Assistant messages and conversation history are stored and sent to the configured processing provider and fallback routes for a reply; processing may be abroad. Do not submit personal or confidential information. You can delete a conversation; automatic cleanup targets conversations inactive for over 31 days, not each message after 31 days. Backups and provider retention are separate.' } },
    { title: { fa: 'داده‌های حساب', en: 'Account data' }, body: {
      fa: 'برای حساب، نام کاربری، ایمیل و هش رمز عبور ذخیره می‌شود. نام نمایشی اختیاری است؛ نام واقعی لازم نیست. ایمیل برای بازیابی حساب و هشدارهای انتخابی شماست. پذیرش ثبت‌نام و نسخه متن ثبت می‌شود. اطلاعات بانکی، مدرک هویت یا داده حساس در فرم‌ها نفرستید.',
      en: 'Accounts store a username, email and password hash. A display name is optional; a legal name is not needed. Email supports account recovery and alerts you enable. Registration acknowledgement and the policy version are recorded. Do not submit bank details, identity documents or sensitive personal information.' } },
    { title: { fa: 'خدمت و امنیت', en: 'Service and security' }, body: {
      fa: 'هشدارها، تنظیمات، پیام‌های پشتیبانی و در صورت فعال‌سازی، اشتراک اعلان مرورگر و مقصد وب‌هوک ذخیره می‌شوند. سوابق ورود شامل زمان و هش نشانی شبکه و مشخصات مرورگر است. میزبان ممکن است نشانی شبکه و مسیر درخواست را در لاگ نگه دارد. هدف، اجرای درخواست شما، پشتیبانی و مقابله با سوءاستفاده است؛ نه بازاریابی.',
      en: 'We store alerts, settings, support messages and, if enabled, browser push subscriptions and webhook destinations. Sign-in records include time and hashed network address and browser details. Hosting logs may contain network addresses and request paths. These uses support your requests, support and abuse prevention, not marketing.' } },
    { title: { fa: 'دریافت‌کنندگان', en: 'Recipients' }, body: {
      fa: 'میزبان، ارائه‌دهنده ایمیل و سرویس اعلان مرورگر ممکن است داده لازم برای خدمت را پردازش کنند. وب‌هوک به مقصد انتخابی شما می‌رود. داده بازار در سرور از منابع بیرونی دریافت می‌شود. نمودار ثالث خودکار بار نمی‌شود؛ پیوند بیرونی تابع سیاست همان سایت است. نام ارائه‌دهندگان و کشور پردازش باید توسط مالک تکمیل شود.',
      en: 'Hosting, email and browser push providers may process data needed for the service. Webhooks go to destinations you choose. Market data is fetched by the server. External charts do not load automatically; linked sites use their own policies. The operator must complete the named provider and processing-country register.' } },
    { title: { fa: 'نگهداری و حقوق شما', en: 'Retention and your rights' }, body: {
      fa: 'خروج به معنی حذف حساب یا نسخه پشتیبان نیست. حذف خودکار همه سوابق شخصی و زمان‌بندی جامع نگهداری هنوز تأیید نشده است. برای دسترسی، اصلاح، حذف یا اعتراض از راه تماس کسب‌وکار استفاده کنید؛ کاربران واردشده می‌توانند تیکت بفرستند. احراز هویت متناسب لازم است. تکلیف قانونی ممکن است حذف را محدود کند؛ پاسخ باید محدودیت و زمان حذف نسخه پشتیبان را روشن کند.',
      en: 'Signing out does not delete an account or backups. Automatic deletion of all personal records and a comprehensive retention schedule are not yet verified. Request access, correction, deletion or objection using the business contact channel; signed-in users can send a support ticket. Proportionate identity checks are needed. Legal retention duties may restrict deletion; the response should explain restrictions and backup expiry.' } },
    { title: { fa: 'انتخاب و تغییر', en: 'Choices and changes' }, body: {
      fa: 'اعلان مرورگر اختیاری است؛ از تنظیمات سایت و مجوز مرورگر خاموش می‌شود. هشدار ایمیل و وب‌هوک را می‌توانید خاموش کنید. ابزار تبلیغات یا تحلیل بازدید در کد بررسی‌شده نصب نیست. امنیت مطلق تضمین نمی‌شود. تغییر مهم هدف پردازش نیاز به اطلاع‌رسانی و در موارد لازم رضایت تازه دارد.',
      en: 'Push is optional; disable it in site settings and browser permissions. Email and webhook alerts can be disabled. No advertising or visitor-analytics tool is installed in the reviewed code. Absolute security is not guaranteed. Material changes to processing purposes require notice and fresh consent where required.' } },
  ],
  terms: [
    { title: { fa: 'مالک و دامنه خدمت', en: 'Operator and service scope' }, body: {
      fa: 'مالک خدمت ایلیا شاکری (Ilia Shakeri)، تهران، ایران است؛ راه تماس iliashkr@gmail.com است. خدمت فعلاً رایگان و برای بازار ایران ارائه می‌شود. اشتراک پولی و گسترش جهانی صرفاً برنامه آینده‌اند؛ پیش از اجرا، شرایط و سیاست‌های مرتبط بازبینی و اعلام می‌شوند. هیچ هزینه یا تمدید خودکاری اکنون فعال نیست.',
      en: 'The operator is Ilia Shakeri (ایلیا شاکری), Tehran, Iran; contact iliashkr@gmail.com. The service is currently free and targets Iran. Paid subscriptions and worldwide expansion are future plans only; relevant terms and policies will be reviewed and announced before launch. No charges or automatic renewal are currently active.' } },
    { title: { fa: 'ماهیت خدمت', en: 'The service' }, body: {
      fa: 'نرخ‌بان ابزار مشاهده نرخ و ثبت هشدار است؛ کیف پول، صرافی یا محل معامله نیست. قیمت، نمودار و تحلیل ممکن است دیر، ناقص یا نادرست باشد. زمان و منبع نرخ را بررسی کنید. محتوا توصیه شخصی سرمایه‌گذاری یا تضمین سود نیست.',
      en: 'Nerkhbaan displays market data and price alerts; it is not a wallet, exchange or trading venue. Prices, charts and analysis can be delayed, incomplete or wrong. Check timestamps and sources. Content is not personal investment advice or a promise of returns.' } },
    { title: { fa: 'حساب و استفاده مجاز', en: 'Accounts and acceptable use' }, body: {
      fa: 'راه تماس قابل دسترس بدهید و رمز را محرمانه نگه دارید. دسترسی غیرمجاز، اختلال، دورزدن محدودیت و محتوای غیرقانونی مجاز نیست. فقط مقصد اعلانی را وارد کنید که اجازه استفاده از آن دارید. دسترسی ممکن است برای سوءاستفاده محدود شود؛ اعتراض از راه پشتیبانی ممکن است.',
      en: 'Use reachable contact details and protect your password. Unauthorized access, disruption, bypassing limits and unlawful submissions are prohibited. Use only notification destinations you may use. Access may be restricted for abuse; contact support to dispute a restriction.' } },
    { title: { fa: 'محتوا و حقوق', en: 'Content and rights' }, body: {
      fa: 'حقوق علائم، تصاویر، نرم‌افزار و داده ثالث متعلق به صاحبان آن‌هاست. نمایش نرخ مجوز بازنشر یا فروش آن نیست. فقط محتوایی بفرستید که اجازه ارسالش را دارید؛ پیام شما برای رسیدگی به درخواست استفاده می‌شود. هیچ بند این متن حقوق الزامی مصرف‌کننده یا مسئولیت غیرقابل اسقاط را حذف نمی‌کند.',
      en: 'Third-party marks, images, software and data belong to their owners. Display is not a licence to redistribute or sell data. Submit only content you may share; messages are used to handle your request. Nothing here removes mandatory consumer rights or liability that cannot lawfully be excluded.' } },
    { title: { fa: 'اختلاف، تغییر و هزینه', en: 'Disputes, changes and charges' }, body: {
      fa: 'اختلاف را از راه تماس کسب‌وکار مطرح کنید. قانون و مرجع صالح به محل واقعی فعالیت و حقوق الزامی کاربر بستگی دارد؛ داوری اجباری یا اسقاط حق شکایت تحمیل نمی‌شود. هزینه و تمدید خودکار بدون اعلام قیمت، مدت، روش لغو و پذیرش صریح نباید فعال شود. شرایط تازه خرید قبلی را عطف‌به‌ماسبق تغییر نمی‌دهد.',
      en: 'Raise disputes through the business contact channel. Governing law and jurisdiction depend on the actual business location and mandatory user protections; no compulsory arbitration or waiver of court access is imposed. Charges or automatic renewal must not start without clear pricing, duration, cancellation rules and express agreement. New terms do not retroactively change an existing purchase.' } },
  ],
  cookies: [
    { title: { fa: 'نشست ضروری', en: 'Necessary sessions' }, body: {
      fa: 'کوکی‌های first-party با نام پیش‌فرض nerkhbaan_session و nerkhbaan_refresh برای ورود و تمدید نشست هستند. مدت پیش‌فرض ۱۵ دقیقه و ۳۰ روز است؛ تنظیم سرور ممکن است متفاوت باشد. مدیریت کوکی نشست جدا دارد. مسدودکردن این کوکی‌ها ورود را مختل می‌کند. خروج، کوکی‌های ورود را پاک می‌کند.',
      en: 'First-party cookies named nerkhbaan_session and nerkhbaan_refresh by default support sign-in and renewal. Default lifetimes are 15 minutes and 30 days; server configuration can differ. Administration has a separate session cookie. Blocking these cookies prevents sign-in. Signing out clears sign-in cookies.' } },
    { title: { fa: 'تنظیمات و کش', en: 'Preferences and cache' }, body: {
      fa: 'ذخیره محلی زبان، پوسته، واحد قیمت و ترتیب نمودار انتخابی شما را تا پاک‌شدن داده سایت نگه می‌دارد. نشان splash-shown تا پایان نشست برگه می‌ماند. سرویس‌ورکر فایل‌های عمومی را برای اجرا و به‌روزرسانی کش می‌کند؛ نه پاسخ حساب و پشتیبانی. داده سایت و مجوز اعلان را از تنظیمات مرورگر می‌توانید پاک کنید.',
      en: 'Local storage remembers your selected language, theme, currency and chart order until site data is cleared. The splash-shown flag lasts for the tab session. A service worker caches public application files for loading and updates, not account or support responses. Clear site data and notification permissions in browser settings.' } },
    { title: { fa: 'رهگیری و رضایت', en: 'Tracking and consent' }, body: {
      fa: 'این نسخه تبلیغات، تحلیل رفتار یا محتوای جاسازی‌شده ثالث بار نمی‌کند؛ بنر «قبول همه کوکی‌ها» ندارد. کوکی ورود برای خدمت درخواستی و ذخیره تنظیمات برای انتخاب خود شماست. افزودن رهگیری نیاز به بازبینی و در موارد لازم رضایت قبلی با رد و پس‌گرفتن آسان دارد.',
      en: 'This version loads no advertising, behavioural analytics or third-party embeds, so it has no “accept all cookies” banner. Sign-in cookies support the requested service; preferences remember your choices. Adding tracking requires review and, where required, prior consent with easy refusal and withdrawal.' } },
  ],
  refunds: [
    { title: { fa: 'وضعیت پرداخت', en: 'Payment status' }, body: {
      fa: 'نرخ‌بان فعلاً رایگان است و اشتراک پولی، خرید یا تمدید خودکار ندارد؛ بنابراین برای استفاده فعلی مبلغ اشتراکی برای بازپرداخت دریافت نمی‌شود. ساخت حساب مجوز برداشت وجه نیست. اشتراک پولی فقط برنامه آینده است. اگر وجهی با نام نرخ‌بان از شما گرفته شده، برای بررسی به iliashkr@gmail.com اطلاع دهید؛ این متن حقوق قانونی شما را حذف نمی‌کند.',
      en: 'Nerkhbaan is currently free, with no paid subscription, checkout or automatic renewal; no subscription fee is collected for current use to refund. Creating an account does not authorize a charge. Paid subscriptions are only a future plan. If someone charged you in Nerkhbaan’s name, contact iliashkr@gmail.com for review; this does not remove your legal rights.' } },
    { title: { fa: 'درخواست رسیدگی', en: 'Request a review' }, body: {
      fa: 'برای پرداخت اشتباه یا لغو، تاریخ، مبلغ و شناسه غیرحساس رسید را از راه تماس کسب‌وکار یا تیکت بفرستید. شماره کامل کارت، رمز یا کد امنیتی نفرستید. فروش پولی تا تعیین هویت فروشنده، مهلت پاسخ، روش لغو و شرایط بازپرداخت نباید آغاز شود.',
      en: 'For a mistaken charge or cancellation, send the date, amount and a non-sensitive receipt reference through the business contact channel or a support ticket. Do not send full card numbers, passwords or security codes. Paid sales must not launch until seller identity, response times, cancellation and refund rules are settled.' } },
    { title: { fa: 'حقوق الزامی', en: 'Mandatory rights' }, body: {
      fa: 'این متن شرط «بدون بازپرداخت» نیست. حق انصراف و استثناهای آن به نوع خدمت و قانون بستگی دارد؛ در ایران مواد ۳۷ و ۳۸ قانون تجارت الکترونیکی باید برای خدمت واقعی بررسی شود. پذیرش عمومی فرم جای رضایت جداگانه لازم برای شروع خدمت در مهلت انصراف نیست.',
      en: 'This is not a “no refunds” rule. Withdrawal rights and exceptions depend on the service and law; for Iran, Articles 37 and 38 of the Electronic Commerce Act need review against the actual service. A general form checkbox does not replace separate consent required for starting a service during a withdrawal period.' } },
  ],
  business: [
    { title: { fa: 'نام خدمت و دامنه', en: 'Service and domain' }, body: { fa: 'نرخ‌بان — nerkhbaan.ir. اطلاع‌رسانی نرخ و هشدار قیمت.', en: 'Nerkhbaan — nerkhbaan.ir. Market information and price alerts.' } },
    { title: { fa: 'هویت و تماس', en: 'Operator and contact' }, body: {
      fa: 'مالک قانونی: ایلیا شاکری (Ilia Shakeri). محل فعالیت: تهران، ایران. ایمیل عمومی پشتیبانی و حریم خصوصی: iliashkr@gmail.com؛ تماس بدون حساب ممکن است. نشانی عمومی پستی نداریم. شناسه ثبت یا مجوز تأییدشده‌ای در این صفحه ارائه نشده؛ درج نام مالک ادعای ثبت شرکت یا داشتن مجوز نیست.',
      en: 'Legal owner: Ilia Shakeri (ایلیا شاکری). Operating location: Tehran, Iran. Public support and privacy email: iliashkr@gmail.com; contact does not require an account. We have no public postal address. No verified registration or licence identifier is provided here; naming the owner is not a claim of incorporation or licensing.' } },
    { title: { fa: 'بازار و هزینه فعلی', en: 'Current market and price' }, body: {
      fa: 'بازار هدف فعلی ایران است. خدمت اکنون رایگان است. ارائه جهانی و اشتراک پولی برنامه آینده هستند و هنوز اجرا نشده‌اند. قبل از دریافت وجه، قیمت، مدت، لغو، بازپرداخت و اطلاعات لازم فروشنده باید اعلام شوند.',
      en: 'The current target market is Iran. The service is free now. Worldwide service and paid subscriptions are future plans, not launched offerings. Pricing, duration, cancellation, refunds and required seller details must be disclosed before taking payment.' } },
  ],
};
