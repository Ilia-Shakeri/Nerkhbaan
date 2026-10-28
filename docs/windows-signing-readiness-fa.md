# نصب ویندوز و مهر ناشر — 2.8.1

<!-- delivery-docs:2.8.16 -->
> مرور سند: ۲۸اکتبر۲۰۲۶؛ منبع/سند **۲.۸.۱۶**، آخرین نصبِ پذیرفته **۲.۸.۱۵**. راهنما؛ وضع جاری در نقشه. عددها، شکست‌ها و قبولی‌های قدیم، شاهد تازه نیستند. [نقشهٔ جاری و فلوچارت](project-completion-roadmap-fa.md) · [فهرست سندها](documentation-index-fa.md).

- [راهِ رایگان،۲۴اکتبر۲۰۲۶]: [بررسی SignPath و Store، شرط و دسترسی](free-windows-signing-2026-10-24.md). هیچ خدمتِ رایگان هنوز این پروژه را نپذیرفته؛ انتخابِ مجوز یا احراز هویت، خودکار انجام نشود. بخش۲.۸.۱ زیر، شاهد تاریخی است.

تاریخ بررسی: 2026-10-11. هدف: Windows x64؛ سازنده: `electron-builder 26.15.3`.

- [گواهی]: گواهی ناشر در مخزن کاربر و سیستم پیدا نشد. راه امضای ابری هم تنظیم نشده. کاربر نبود گواهی و سرویس را تأیید کرد. مهر معتبر هنوز سد دارد.
- [نسخه]: خاموش بودن ویرایش و امضای فایل رفع شد. فایل برنامه اکنون نام و نسخهٔ پروژه و نشان نرخ‌بان می‌گیرد؛ نسخهٔ موتور جای نسخهٔ محصول نمی‌نشیند.
- [ساخت]: `package:win` به مسیر امضا می‌رود. نبود امضا، ساخت را رد می‌کند. مسیر بی‌امضا نام و پوشهٔ جدا دارد.
- [قبولی]: امضای برنامه، نصب‌کننده و حذف‌کننده باید `Valid` باشد؛ ناشر دقیق، EKU امضای کد و مهر زمان هم باید پاس شود. hash تنها، مهر ناشر نیست.
- [دامنه]: این بررسی ویندوز است. نصب macOS/Linux، امضای ناشر آن‌ها و اعتبار SmartScreen هنوز شاهد ندارند.

شاهد اجرای همین نسخه، در همین Windows x64:

| بررسی | نتیجه | رسید بیرون پروژه |
|---|---|---|
| ساخت NSIS و metadata نسخهٔ `2.8.1` و نشان پروژه | پاس؛ فایل بی‌امضا | `desktop/2.8.1/unsigned-final.json` |
| نصب per-user در مسیر موقت خود آزمون | خروجی صفر؛ فایل نصب‌شده با candidate برابر | `desktop/2.8.1/unsigned-installer-acceptance.json` |
| اجرای برنامهٔ نصب‌شده | origin امن؛ نشان ۲۰۰؛ مسیر بد ۴۰۳/۴۰۴؛ ورود و خروج UI ساختگی؛ نشست رمز‌شده؛ حذف فایل نشست | `desktop/2.8.1/unsigned-installed-runtime.json` |
| حذف نصب و حفظ دستگاه کاربر | مسیر، کلیدهای registry و پروفایل آزمون پاک؛ پروفایل معمولی حفظ | `desktop/2.8.1/unsigned-installer-acceptance.json` |
| امضای installer/app/uninstaller | هر سه `NotSigned`؛ قبولی امضا رد | همان رسید نصب و `unsigned-signature-rejection.json` |
| ساخت با `forceCodeSigning=true` | با نبود گواهی رد؛ بستهٔ امضاشده ساخته نشد | `desktop/2.8.1/signed-gate.json` |
| خود ابزار بررسی امضا | فایل معتبر دیگر با هویت خودش پاس؛ ناشر غلط، thumbprint غلط و بستهٔ بی‌امضا رد | رسیدهای `verifier-*-control.json`؛ امضای محصول را ثابت نمی‌کنند |

نام candidate: `Nerkhbaan-2.8.1-win-x64-UNSIGNED.exe`؛ حجم: `103909264` بایت؛ SHA-256:

```text
6f19ee853ed01ae92e40b0c3b45af1c01b22f66f18decc7f1295b4d515830504
```

رسیدهای خصوصی و candidate در پوشهٔ بیرون مخزن `Nerkhbaan-Delivery/remaining-20261011/desktop/2.8.1/` هستند. میان‌بر و اجرای خودکار برای candidate آزمون خاموش بود. قبل از نصب، نصب یا برنامهٔ باز نرخ‌بان روی دستگاه نبود. آزمون با حساب واقعی و credential واقعی اجرا نشد؛ از نخستین شروع، proxy محلیِ خاموش خروج شبکه را بست و fixture فقط پاسخ ساختگی داد. امضای trusted publisher، نصب روی دستگاه دیگر و گواهی ناشر با این شاهد ادعا نشود. شاهد نسخهٔ `2.8.0` جدا نگه داشته شد.

فرمان بی‌امضا برای آزمون؛ خروجی برای پذیرش امضای ناشر قابل قبول نیست:

```powershell
npm.cmd run package:win:unsigned --workspace=nerkhbaan-desktop
```

فرمان امضا، فقط پس از آماده شدن گواهی واقعی ناشر و کلید قابل استفاده:

```powershell
npm.cmd run package:win:signed --workspace=nerkhbaan-desktop
```

کلید و رمز در فایل پروژه یا فرمان ثبت نشود. گواهی واقعی در مخزن امن ویندوز/سخت‌افزار یا سرویس مجاز ناشر آماده شود. برای گواهی موجود در مخزن، شناسهٔ عمومی دقیق آن قابل انتخاب است:

```powershell
npm.cmd run package:win:signed --workspace=nerkhbaan-desktop -- --config.win.signtoolOptions.certificateSha1=THUMBPRINT_FROM_REAL_CERTIFICATE
```

نام و شناسه از گواهی واقعی خوانده شود؛ هویت ناشر ساخته نشود. امکان سرویس ابری به کشور، نوع ناشر و احراز هویت بستگی دارد. مجاز بودن آن برای این ناشر تأیید نشده. خرید یا ثبت‌نام انجام نشده.

بررسی نصب‌کننده و فایل اصلی، پیش از نصب:

```powershell
$releaseVersion = (Get-Content VERSION -Raw).Trim()
$signatureArgs = @{
  ArtifactPath = @(
    ".\apps\desktop\release\Nerkhbaan Setup $releaseVersion.exe",
    '.\apps\desktop\release\win-unpacked\Nerkhbaan.exe'
  )
  ExpectedPublisher = 'FULL_SUBJECT_FROM_REAL_CERTIFICATE'
  ExpectedSignerThumbprint = 'THUMBPRINT_FROM_REAL_CERTIFICATE'
  ExpectedVersion = $releaseVersion
  ReceiptPath = "C:\ReleaseEvidence\windows-signature-$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ')).json"
}
.\scripts\verify-windows-signature.ps1 @signatureArgs
if ($LASTEXITCODE -ne 0) { throw 'Publisher signature gate failed.' }
```

برای هر تلاش، `ReceiptPath` تازه بدهید؛ فایل موجود بازنویسی نشود. نسخهٔ Windows با revision صفر، مانند `2.8.13.0`، با انتشار `2.8.13` برابر است؛ revision غیرصفر یا نسخهٔ دیگر رد شود. hash فایل پیش و پسِ سنجش برابر باشد. جدول و رسیدهای۲.۸.۱ بالا تاریخی‌اند. [شاهدِ تازهٔ گام۵](step5-acceptance-2026-10-24.md).

شرط قبولی: `accepted=true` برای هر دو فایل و کل رسید؛ خروجی صفر. `NotSigned`، ناشر دیگر، گواهی خودساخته، نبود مهر زمان یا خطای trust رد شود. اعتماد در همین میزبان سنجیده می‌شود؛ رفتار همهٔ دستگاه‌ها یا نبود هشدار SmartScreen ثابت نمی‌شود. شناسهٔ گواهی برای تمدید باید با شاهد ناشر تازه شود.

نصب آزمون در Windows VM پاک یا حساب جدا انجام شود؛ نصب فعلی کاربر بازنویسی نشود. مسیر نصب، برنامه و uninstaller از قبل نباشد. نصب به حساب آزمون محدود شود. پس از نصب، همان verifier روی `Nerkhbaan.exe` و `Uninstall Nerkhbaan.exe` اجرا شود؛ ناشر همان باشد.

آزمون runtime نصب‌شده، با پروفایل موقت و حساب ساختگی:

```powershell
$env:NERKHBAAN_DESKTOP_EXECUTABLE = 'C:\ReleaseAcceptance\Nerkhbaan.exe'
$env:NERKHBAAN_DESKTOP_SMOKE_RECEIPT = 'C:\ReleaseEvidence\installed-runtime.json'
npm.cmd run test:desktop
Remove-Item Env:\NERKHBAAN_DESKTOP_EXECUTABLE
Remove-Item Env:\NERKHBAAN_DESKTOP_SMOKE_RECEIPT
```

آزمون، origin محلی امن، فایل نشان، منع خروج از مسیر، نگهداری رمز‌شدهٔ نشست، ورود ساختگی و خروج از دکمهٔ برنامه را می‌سنجد. درخواست شبکه در این آزمون رهگیری و پاسخ ساختگی می‌گیرد. ورود واقعی سرور با این شاهد ادعا نشود. پروفایل آزمون پس از پایان پاک شود. حذف نصب آزمون و نبود کلید registry، میان‌بر و مسیر نصب هم جدا ثبت شود.

مدرک امضای معتبر لازم برای بستن سد: گواهی واقعی ناشر یا سرویس آماده، Subject و thumbprint عمومی، سپس رسید `accepted=true` برای installer/app/uninstaller و رسید نصب/اجرای واقعی همان بسته. گواهی آزمایشی خودساخته این سد را نمی‌بندد.

مرجع‌ها: [تنظیم Windows برای نسخهٔ ۲۶](https://www.electron.build/v26/docs/win/)، [امضای Windows برای نسخهٔ ۲۶](https://www.electron.build/v26/docs/features/code-signing/code-signing-win/)، [ساخت fail با نبود امضا](https://www.electron.build/v26/docs/features/code-signing/)، [بررسی Authenticode در Windows](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.security/get-authenticodesignature?view=powershell-7.5).
