export const INDIA_MARKET_TIME_ZONE = "Asia/Kolkata";
export const HOST_TIMEZONE_STORAGE_KEY = "tradebrain_host_timezone";
export const HOST_TIMEZONE_CONFIRMED_KEY = "tradebrain_host_timezone_confirmed";

export type ZonedParts = {
  year: string;
  month: string;
  day: string;
  hour: number;
  minute: number;
  second: number;
};

export function detectHostTimeZone(): string {
  if (typeof Intl === "undefined") return "UTC";
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

export function getZonedParts(date: Date, timeZone: string): ZonedParts {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);

  const value = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value || "";

  return {
    year: value("year"),
    month: value("month"),
    day: value("day"),
    hour: Number(value("hour") || 0),
    minute: Number(value("minute") || 0),
    second: Number(value("second") || 0),
  };
}

export function getIndiaMarketDate(date: Date = new Date()): string {
  const parts = getZonedParts(date, INDIA_MARKET_TIME_ZONE);
  return `${parts.year}-${parts.month}-${parts.day}`;
}

export function formatClock(date: Date, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
    timeZoneName: "short",
  }).format(date);
}

export function getIndiaMarketGreeting(date: Date = new Date()): string {
  const { hour } = getZonedParts(date, INDIA_MARKET_TIME_ZONE);
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export function getIndiaMarketDayContext(date: Date = new Date()): string {
  const { hour, minute } = getZonedParts(date, INDIA_MARKET_TIME_ZONE);
  const totalMin = hour * 60 + minute;

  if (totalMin < 9 * 60) return "India market opens at 9:15 AM IST. Good time to plan your trades.";
  if (totalMin < 9 * 60 + 15) return "India market opens in minutes. Review overnight news and top picks.";
  if (totalMin < 10 * 60 + 30) return "India opening hour — watch for gaps and early breakouts.";
  if (totalMin < 14 * 60) return "India mid-session — most stable period. Good for swing trade entries.";
  if (totalMin < 15 * 60 + 10) return "India closing phase — manage live setups carefully.";
  if (totalMin < 15 * 60 + 15) return "No fresh intraday entries after 3:10 PM IST; flatten by 3:15 PM IST.";
  if (totalMin < 15 * 60 + 30) return "Intraday hard-exit window has passed; India market is nearing close.";
  if (totalMin < 16 * 60) return "India market closed. Review today's trades and prep for tomorrow.";
  return "India market closed. After-market study/replay period.";
}
