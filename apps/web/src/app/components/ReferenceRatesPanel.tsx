import React, { useEffect, useRef, useState } from 'react';
import { useAppContext } from '../context/AppContext';
import { getReferenceRates, type ReferenceRateItem, type ReferenceRatesResponse, type ReferenceTimeframe } from '../services/api';
import { formatHistoryTimestamp } from '../services/history-time';
import { currentRightsRevision, PRICING_RIGHTS_EVENT, rightsArePending, safeAttributions } from '../services/price-stream';
import { logoutGeneration, logoutIsPending, subscribeLogoutStatus } from '../services/logout-state';

const MINUTE = 60_000;
const CARD_KEYS = { GOLD_24K_REFERENCE_TOMAN_GRAM: 'gold24', BTC_USD_IRAN_REFERENCE: 'btc', USDT_USD_IRAN_REFERENCE: 'usdt' } as const;

export function ReferenceRatesPanel() {
  const { language, theme, isAuthenticated } = useAppContext();
  const dark = theme === 'dark';
  const section = useRef<HTMLElement>(null);
  const [timeframe, setTimeframe] = useState<ReferenceTimeframe>('30d');
  const [data, setData] = useState<ReferenceRatesResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [now, setNow] = useState(Date.now());
  const lastRequest = useRef<Partial<Record<ReferenceTimeframe, number>>>({});
  const cache = useRef<Partial<Record<ReferenceTimeframe, ReferenceRatesResponse>>>({});
  const pending = useRef<Promise<void> | null>(null);

  useEffect(() => {
    let active = true;
    let inView = typeof IntersectionObserver === 'undefined';
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    const mounted = Date.now();
    const visible = () => active && isAuthenticated && inView && document.visibilityState !== 'hidden' && !logoutIsPending();
    const schedule = (delay: number) => {
      clearTimeout(timer);
      if (visible()) timer = setTimeout(() => void load(), delay);
    };
    const load = async () => {
      if (!visible()) return;
      if (pending.current) { void pending.current.then(() => schedule(0)); return; }
      if (!currentRightsRevision() && Date.now() - mounted < 1000) { schedule(100); return; }
      const remaining = MINUTE - (Date.now() - (lastRequest.current[timeframe] ?? 0));
      if (remaining > 0) { schedule(remaining); return; }
      lastRequest.current[timeframe] = Date.now();
      controller = new AbortController();
      const request = controller;
      const generation = logoutGeneration();
      const work = (async () => {
        try {
          const reply = await getReferenceRates(timeframe, request.signal);
          if (!active || request.signal.aborted || logoutIsPending() || generation !== logoutGeneration()
              || rightsArePending() || reply.rights_revision !== currentRightsRevision()) return;
          cache.current[timeframe] = reply;
          setData(reply); setFailed(false); setNow(Date.now());
        } catch {
          if (active && !request.signal.aborted && !logoutIsPending()) { setData(null); setFailed(true); }
        }
      })();
      pending.current = work;
      await work;
      if (pending.current === work) pending.current = null;
      schedule(Math.max(0, MINUTE - (Date.now() - (lastRequest.current[timeframe] ?? 0))));
    };
    const reset = (event?: Event) => {
      cache.current = {};
      setData(null); setFailed(false);
      const origin = (event as CustomEvent<{ origin?: string }> | undefined)?.detail?.origin;
      if (logoutIsPending() || origin === 'socket') controller?.abort();
      if (visible()) void load();
    };
    const visibility = () => {
      setNow(Date.now());
      if (visible()) void load();
      else { clearTimeout(timer); controller?.abort(); }
    };
    const observer = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver(entries => {
      inView = entries.some(entry => entry.isIntersecting);
      visibility();
    });
    if (section.current) observer?.observe(section.current);
    const previous = cache.current[timeframe];
    setData(previous?.rights_revision === currentRightsRevision() ? previous : null);
    setFailed(false);
    window.addEventListener(PRICING_RIGHTS_EVENT, reset);
    document.addEventListener('visibilitychange', visibility);
    const unsubscribe = subscribeLogoutStatus(() => { if (logoutIsPending()) reset(); });
    const clock = setInterval(() => { if (visible()) setNow(Date.now()); }, 15_000);
    if (inView) void load();
    return () => {
      active = false; controller?.abort(); clearTimeout(timer); clearInterval(clock); observer?.disconnect();
      window.removeEventListener(PRICING_RIGHTS_EVENT, reset);
      document.removeEventListener('visibilitychange', visibility);
      unsubscribe();
    };
  }, [isAuthenticated, timeframe]);

  const fa = language === 'fa';
  const localize = (value: string) => fa ? value.replace(/\d/g, digit => '۰۱۲۳۴۵۶۷۸۹'[Number(digit)]) : value;
  const number = (value: number, currency: 'TOMAN' | 'USD') => new Intl.NumberFormat(fa ? 'fa-IR' : 'en-US',
    currency === 'TOMAN' && value >= 1 ? { maximumFractionDigits: 0 } : { maximumSignificantDigits: 10 }).format(value);
  const result = isAuthenticated && data?.timeframe === timeframe && data.rights_revision === currentRightsRevision()
    && !rightsArePending() && !logoutIsPending() ? data : null;
  const credits = result ? safeAttributions([
    ...result.attributions, ...result.references.map(item => item.attribution),
    ...result.references.flatMap(item => item.history.map(point => point.attribution)),
  ]) : [];
  const muted = dark ? 'text-[#A89668]' : 'text-[#765C1F]';
  const foreground = dark ? 'text-[#E8D9AE]' : 'text-[#3B2E13]';
  const card = dark ? 'border-white/10 bg-[#0E0E0E]' : 'border-black/10 bg-white';

  const renderCard = (item: ReferenceRateItem) => {
    const current = item.current;
    const checked = Date.parse(result!.checked_at);
    const elapsed = Number.isFinite(checked) ? Math.max(0, (now - checked) / 1000) : 0;
    const age = typeof current.age_seconds === 'number' && Number.isFinite(current.age_seconds) ? current.age_seconds + elapsed : null;
    const hasPrice = typeof current.price === 'number' && Number.isFinite(current.price) && current.price > 0
      && current.status !== 'unavailable_reference' && age !== null && age <= current.maximum_reference_age_seconds;
    const delayed = current.status === 'delayed_reference' || (age !== null && age > current.freshness_limit_seconds);
    const history = item.history.filter(point => Number.isFinite(point.price) && point.price > 0).slice(-365);
    const gold = item.method === 'published_reference';
    const ageText = age === null ? fa ? 'سن نرخ نامعلوم' : 'Rate age unknown'
      : age < 60 ? fa ? 'کمتر از یک دقیقه' : 'Less than a minute'
        : `${localize(String(Math.floor(age / 60)))} ${fa ? 'دقیقه' : 'minutes'}`;
    const unit = item.currency === 'TOMAN' ? fa ? 'تومان / گرم' : 'Toman / gram' : 'USD';
    return <article key={item.instrument_id} data-reference-card={CARD_KEYS[item.instrument_id]} className={`min-w-0 rounded-2xl border p-4 ${card}`}>
      <h3 className={`text-base font-semibold ${foreground}`}>{fa ? item.label_fa : item.label_en}</h3>
      <div className="mt-3 flex flex-wrap gap-2 text-xs">
        <span className={`rounded-full px-2 py-1 ${dark ? 'bg-amber-500/10 text-amber-200' : 'bg-amber-50 text-amber-900'}`}>
          {!hasPrice ? fa ? 'در دسترس نیست' : 'Unavailable' : delayed ? fa ? 'مرجع با تأخیر' : 'Delayed reference' : fa ? 'مرجع تازه' : 'Fresh reference'}
        </span>
        {hasPrice && <span className={`rounded-full border px-2 py-1 ${muted}`}>
          {current.storage_fallback ? fa ? 'از دادهٔ ذخیره‌شده' : 'From saved data'
            : current.persistence_status === 'persisted' ? fa ? 'ذخیره‌شده' : 'Saved' : fa ? 'ذخیره نشده' : 'Not saved'}
        </span>}
      </div>
      <p className={`mt-3 text-2xl font-bold tabular-nums ${foreground}`} data-reference-price dir="ltr">
        {hasPrice ? number(current.price!, item.currency) : '—'} <span className={`text-xs font-medium ${muted}`}>{unit}</span>
      </p>
      <p className={`mt-3 text-xs leading-6 ${muted}`}>
        {gold
          ? fa ? 'مرجع منتشرشدهٔ ۲۴ عیار؛ خلوص دقیق تأیید نشده و قیمت شمش ۹۹۹۹ نیست.' : 'Published 24K reference. Exact purity is unconfirmed; this is not a 9999 bullion quote.'
          : fa ? 'قیمت تومانِ ایران ÷ نرخ دلارِ همان منبع؛ ارزش محاسباتی ایران، نه قیمت بازار جهانی یا سنجش برابری تتر.' : 'Iranian Toman price ÷ the same source’s dollar rate. An Iranian valuation, not a global exchange quote or a Tether parity measure.'}
      </p>
      {!gold && hasPrice && current.inputs.length > 0 && <p className={`mt-1 text-xs tabular-nums ${muted}`} dir="ltr" data-reference-inputs>
        {current.inputs.map(input => typeof input.price === 'number' && Number.isFinite(input.price) ? number(input.price, 'TOMAN') : '—').join(' ÷ ')} Toman
      </p>}
      <div className={`mt-3 border-t pt-3 text-xs leading-6 ${muted}`}>
        <p>{fa ? 'آخرین تغییر نرخ‌های منبع' : 'Source rates last changed'}</p>
        <p data-reference-source-clock dir="ltr">
          {current.source_date ? localize(current.source_date) : '—'}
          {current.source_time ? ` · ${localize(current.source_time)}` : ` · ${fa ? 'ساعت نامعلوم' : 'Time unknown'}`}
          {` (${fa ? 'شمسی، تهران' : 'Jalali, Tehran'})`}
        </p>
        <p>{fa ? 'سن نرخ: ' : 'Rate age: '}{ageText} · {fa ? 'ساعت معامله نامعلوم' : 'Trade time unknown'}</p>
      </div>
      <details className={`mt-3 border-t pt-3 text-xs ${muted}`}>
        <summary className={`cursor-pointer rounded py-1 font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${foreground}`}>
          {fa ? 'آرشیو روزانه' : 'Daily history'} ({localize(String(history.length))})
        </summary>
        <p className="mt-2 leading-6">{fa ? 'پایانی روز؛ ساعت ثبت موجود نیست. فقط روزهای دارای داده نمایش داده می‌شوند.' : 'Daily close; observation time unavailable. Only published days are shown.'}</p>
        {item.history_status === 'partial' && <p className="mt-1">{fa ? 'بخشی از آرشیو در دسترس است.' : 'Some history is unavailable.'}</p>}
        {history.length === 0 ? <p className="mt-2">{fa ? 'دادهٔ روزانه موجود نیست.' : 'No daily history available.'}</p> :
          <div className="mt-2 max-h-64 overflow-auto rounded-lg border border-current/20">
            <table className="w-full text-start tabular-nums">
              <caption className="sr-only">{fa ? `${item.label_fa}؛ تاریخ شمسی، تهران` : `${item.label_en}; Jalali dates, Tehran`}</caption>
              <thead><tr><th className="p-2 text-start">{fa ? 'روز (شمسی)' : 'Day (Jalali)'}</th><th className="p-2 text-start">{unit}</th></tr></thead>
              <tbody>{history.map(point => <tr key={point.source_date}>
                <td className="p-2"><time dateTime={point.timestamp} title={formatHistoryTimestamp(new Date(point.timestamp), language, point)}>{localize(point.source_date)}</time></td>
                <td className="p-2" dir="ltr">{number(point.price, item.currency)}</td>
              </tr>)}</tbody>
            </table>
          </div>}
      </details>
    </article>;
  };

  return <section ref={section} aria-labelledby="reference-rates-title" data-reference-panel className={`rounded-3xl border p-4 sm:p-5 ${dark ? 'border-[#D4AF37]/20 bg-[#121008]' : 'border-[#D4AF37]/30 bg-[#FFFBF0]'}`}>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 id="reference-rates-title" className={`text-lg font-semibold ${foreground}`}>{fa ? 'نرخ‌های مرجع' : 'Reference rates'}</h2>
        <p className={`mt-1 max-w-3xl text-xs leading-6 ${muted}`}>{fa ? 'مرجع‌های منتشرشده و محاسباتی ایران؛ مستقل از قیمت‌های بازار بالا. این بخش فقط برای مشاهده است و هشدار قیمت نمی‌سازد.' : 'Published and calculated Iranian references, separate from the market prices above. Read-only; these values do not trigger price alerts.'}</p>
      </div>
      <label className={`flex items-center gap-2 text-xs ${muted}`}>
        {fa ? 'بازهٔ آرشیو' : 'History period'}
        <select aria-label={fa ? 'بازهٔ آرشیو' : 'History period'} value={timeframe} onChange={event => setTimeframe(event.target.value as ReferenceTimeframe)} className={`rounded-lg border px-2 py-2 ${card} ${foreground}`}>
          <option value="30d">{fa ? '۳۰ روز' : '30 days'}</option><option value="1y">{fa ? '۱ سال' : '1 year'}</option>
        </select>
      </label>
    </div>
    {!result ? failed ? <p role="alert" className={`mt-4 text-sm ${muted}`}>{fa ? 'نرخ‌های مرجع دریافت نشد. هنگام نمایش، هر دقیقه دوباره بررسی می‌شود.' : 'Reference rates could not be loaded. Retrying once a minute while this panel is visible.'}</p>
      : <div role="status" className="mt-4"><span className={`text-xs ${muted}`}>{fa ? 'در انتظار دادهٔ مرجع…' : 'Waiting for reference data…'}</span><div aria-hidden="true" className="mt-3 grid gap-3 md:grid-cols-3">{[0, 1, 2].map(key => <div key={key} className={`h-32 rounded-2xl border ${card}`} />)}</div></div>
      : <div className="mt-4 grid gap-3 md:grid-cols-3">{result.references.filter(item => Object.prototype.hasOwnProperty.call(CARD_KEYS, item.instrument_id)).map(renderCard)}</div>}
    {credits.length > 0 && <p className={`mt-4 text-xs ${muted}`}>{fa ? 'منبع: ' : 'Source: '}{credits.map((credit, index) => <React.Fragment key={credit.url}>{index > 0 ? ' · ' : ''}<a href={credit.url} target="_blank" rel="noopener noreferrer" className="underline underline-offset-4">{credit.label}</a></React.Fragment>)}</p>}
  </section>;
}
