"use client";

import { useEffect, useMemo, useState } from "react";
import {
  detectHostTimeZone,
  formatClock,
  HOST_TIMEZONE_CONFIRMED_KEY,
  HOST_TIMEZONE_STORAGE_KEY,
  INDIA_MARKET_TIME_ZONE,
} from "@/lib/market-time";

const COMMON_TIME_ZONES = [
  "America/Toronto",
  "America/Vancouver",
  "America/New_York",
  "Europe/London",
  "Asia/Dubai",
  "Asia/Kolkata",
  "UTC",
];

export function MarketTimeBar() {
  const [now, setNow] = useState<Date | null>(null);
  const [detectedTimeZone, setDetectedTimeZone] = useState("UTC");
  const [hostTimeZone, setHostTimeZone] = useState("UTC");
  const [confirmed, setConfirmed] = useState(true);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    const detected = detectHostTimeZone();
    const stored = window.localStorage.getItem(HOST_TIMEZONE_STORAGE_KEY);
    const storedConfirmed = window.localStorage.getItem(HOST_TIMEZONE_CONFIRMED_KEY) === "1";

    setDetectedTimeZone(detected);
    setHostTimeZone(stored || detected);
    setConfirmed(Boolean(stored && storedConfirmed));
    setNow(new Date());

    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const options = useMemo(
    () => Array.from(new Set([detectedTimeZone, hostTimeZone, ...COMMON_TIME_ZONES])).filter(Boolean),
    [detectedTimeZone, hostTimeZone],
  );

  const saveHostTimeZone = (timeZone: string) => {
    setHostTimeZone(timeZone);
    setConfirmed(true);
    setEditing(false);
    window.localStorage.setItem(HOST_TIMEZONE_STORAGE_KEY, timeZone);
    window.localStorage.setItem(HOST_TIMEZONE_CONFIRMED_KEY, "1");
  };

  if (!now) {
    return <div className="h-11 border-b border-border bg-card/80" aria-hidden="true" />;
  }

  return (
    <div className="border-b border-border bg-card/80 px-6 py-2 text-xs">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <div>
          <span className="font-semibold">Your time</span>
          <span className="ml-2 text-muted-foreground">{formatClock(now, hostTimeZone)}</span>
          <button
            type="button"
            className="ml-2 underline underline-offset-2 text-muted-foreground hover:text-foreground"
            onClick={() => setEditing((value) => !value)}
          >
            Change
          </button>
        </div>

        <div className="h-4 w-px bg-border hidden sm:block" />

        <div>
          <span className="font-semibold">India market time</span>
          <span className="ml-2 text-muted-foreground">{formatClock(now, INDIA_MARKET_TIME_ZONE)}</span>
          <span className="ml-2 rounded border border-border px-1.5 py-0.5 text-[10px] font-semibold">FIXED IST</span>
        </div>
      </div>

      {!confirmed && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2">
          <span>
            Operating timezone detected as <strong>{detectedTimeZone}</strong>. Use this for your local clock?
          </span>
          <button
            type="button"
            className="rounded bg-foreground px-2 py-1 text-background"
            onClick={() => saveHostTimeZone(detectedTimeZone)}
          >
            Yes, use it
          </button>
          <button
            type="button"
            className="rounded border border-border px-2 py-1"
            onClick={() => setEditing(true)}
          >
            Change
          </button>
          <span className="text-muted-foreground">
            This never changes NSE/BSE timing; Indian market logic stays on IST.
          </span>
        </div>
      )}

      {editing && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <label htmlFor="tradebrain-host-timezone" className="text-muted-foreground">
            Operating timezone
          </label>
          <select
            id="tradebrain-host-timezone"
            value={hostTimeZone}
            onChange={(event) => setHostTimeZone(event.target.value)}
            className="rounded border border-border bg-background px-2 py-1"
          >
            {options.map((timeZone) => (
              <option key={timeZone} value={timeZone}>{timeZone}</option>
            ))}
          </select>
          <button
            type="button"
            className="rounded bg-foreground px-2 py-1 text-background"
            onClick={() => saveHostTimeZone(hostTimeZone)}
          >
            Save
          </button>
          <button
            type="button"
            className="rounded border border-border px-2 py-1"
            onClick={() => setEditing(false)}
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
