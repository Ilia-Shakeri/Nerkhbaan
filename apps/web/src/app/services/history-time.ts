export type HistoryTimeInfo = {
  timestamp_precision?: string | null;
  timestamp_role?: string | null;
  source_observation_time_known?: boolean | null;
  source_timezone?: string | null;
  source_calendar?: string | null;
  source_date?: string | null;
};

export const isDailyHistory = (info?: HistoryTimeInfo | null): boolean =>
  info?.timestamp_precision === 'day' || info?.timestamp_role === 'day_bucket_start';

export function historyTimeInfoForCurrency(
  point: HistoryTimeInfo & { time_info_usd?: HistoryTimeInfo | null; time_info_toman?: HistoryTimeInfo | null },
  mode: 'usd' | 'toman',
): HistoryTimeInfo {
  return (mode === 'usd' ? point.time_info_usd : point.time_info_toman) ?? point;
}

export function formatHistoryTimestamp(
  date: Date,
  language: 'fa' | 'en',
  info?: HistoryTimeInfo | null,
  tick = false,
): string {
  if (!Number.isFinite(date.getTime())) return '';
  const daily = isDailyHistory(info);
  const text = new Intl.DateTimeFormat(language === 'fa' ? 'fa-IR' : 'en-GB', {
    timeZone: 'Asia/Tehran',
    ...(tick ? {} : { year: 'numeric' }),
    month: tick ? 'short' : '2-digit',
    day: tick ? 'numeric' : '2-digit',
    ...(daily ? {} : { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }),
  } as Intl.DateTimeFormatOptions).format(date);
  if (!daily || tick) return text;
  return `${text} · ${language === 'fa' ? 'پایانی روز؛ ساعت ثبت موجود نیست' : 'Daily close; observation time unavailable'}`;
}
