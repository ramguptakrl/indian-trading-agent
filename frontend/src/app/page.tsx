"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Clock3,
  Crosshair,
  Database,
  OctagonMinus,
  RefreshCw,
  ShieldCheck,
  Target,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getAnalysisHistory, getAnalysisResult, getMarketStatus, getQuote } from "@/lib/api";
import { getIndiaMarketDate, getIndiaMarketDayContext, getIndiaMarketGreeting } from "@/lib/market-time";
import type { TradeBrainAdvisory } from "@/lib/types";

const BSE_TICKER = "BSE";

type QuoteState = {
  price?: number;
  change?: number;
  change_percent?: number;
  open?: number;
  high?: number;
  low?: number;
  prev_close?: number;
  volume?: number;
  price_source?: string;
  fallback_used?: boolean;
  fallback_reason?: string;
};

type MarketState = {
  session?: string;
  is_trading_day?: boolean;
  nifty?: { price?: number; change?: number; change_percent?: number };
  banknifty?: { price?: number; change?: number; change_percent?: number };
};

type ModePlan = {
  taskId: string;
  tradeDate: string;
  signal: string;
  advisory: TradeBrainAdvisory;
};

function money(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `₹${value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function humanize(value?: string | null) {
  return value ? value.replaceAll("_", " ") : "—";
}

function strictMode(advisory?: TradeBrainAdvisory | null): string | null {
  const geometryMode = advisory?.trade_geometry?.mode;
  if (geometryMode === "INTRADAY" || geometryMode === "SWING") return geometryMode;
  const parsed = advisory?.ai_candidate?.mode;
  return parsed === "INTRADAY" || parsed === "SWING" ? parsed : null;
}

function strictNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function geometry(plan: ModePlan | null) {
  if (!plan) return { direction: null, entry: null, stop: null, target: null, rr: null };
  const advisory = plan.advisory;
  const parsed = advisory.ai_candidate || {};
  return {
    direction: advisory.trade_geometry?.direction || (typeof parsed.direction === "string" ? parsed.direction : null),
    entry: advisory.trade_geometry?.entry ?? strictNumber(parsed.entry),
    stop: advisory.trade_geometry?.stop_loss ?? strictNumber(parsed.stop_loss),
    target: advisory.trade_geometry?.take_profit ?? strictNumber(parsed.take_profit),
    rr: advisory.trade_geometry?.gross_reward_risk ?? advisory.gate?.reward_risk ?? null,
  };
}

function Level({ icon: Icon, label, value }: { icon: any; label: string; value: number | null }) {
  return (
    <div className="rounded-lg border bg-background p-3">
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Icon className="h-3.5 w-3.5" /> {label}
      </div>
      <div className="mt-1 font-semibold tabular-nums">{money(value)}</div>
    </div>
  );
}

function ModeDecisionCard({ mode, plan }: { mode: "INTRADAY" | "SWING"; plan: ModePlan | null }) {
  const g = geometry(plan);
  const hasAllLevels = g.entry != null && g.stop != null && g.target != null;
  const finalStatus = plan?.advisory?.final_status || null;
  const gatePassed = finalStatus === "ADVISORY_CANDIDATE_PASS";
  const blocked = Boolean(finalStatus?.startsWith("BLOCK"));
  const signal = plan?.signal || "WAIT";
  const isShort = g.direction === "SHORT" || signal === "SHORT_CANDIDATE";
  const DirectionIcon = isShort ? TrendingDown : TrendingUp;

  return (
    <Card className={blocked ? "border-amber-300" : gatePassed ? "border-green-300" : "border-border"}>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              {mode}
              <Badge variant="outline">{mode === "INTRADAY" ? "Same session" : "LONG-only delivery"}</Badge>
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              {mode === "INTRADAY"
                ? "No fresh entries from 15:10 IST · intended flat by 15:15 IST"
                : "Own-cash swing only · no MTF/funded delivery"}
            </p>
          </div>
          <Badge
            variant="outline"
            className={gatePassed ? "border-green-300 text-green-700" : blocked ? "border-amber-300 text-amber-700" : ""}
          >
            {plan ? humanize(signal) : "WAIT"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {plan ? (
          <>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {g.direction && (
                <Badge variant="outline">
                  <DirectionIcon className="mr-1 h-3 w-3" /> {g.direction}
                </Badge>
              )}
              <Badge variant="outline">{humanize(finalStatus || "RESEARCH ONLY")}</Badge>
              {g.rr != null && <Badge variant="outline">Gross R:R {g.rr.toFixed(2)}:1</Badge>}
            </div>

            {hasAllLevels ? (
              <div className="grid grid-cols-3 gap-2">
                <Level icon={Crosshair} label="Entry" value={g.entry} />
                <Level icon={OctagonMinus} label="Stop-Loss" value={g.stop} />
                <Level icon={Target} label="Primary Target" value={g.target} />
              </div>
            ) : (
              <div className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
                No complete validated Entry / Stop / Primary Target geometry is stored for this {mode.toLowerCase()} result.
                Trade Brain will not invent missing levels.
              </div>
            )}

            {!gatePassed && (
              <div className="flex items-start gap-2 rounded-lg bg-amber-50 p-3 text-xs text-amber-800">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  These are research levels only. The deterministic Trade Brain gate has not produced a live pass for this stored plan.
                </span>
              </div>
            )}

            {plan.advisory.reason && (
              <p className="text-xs text-muted-foreground">{plan.advisory.reason}</p>
            )}
          </>
        ) : (
          <div className="rounded-lg border border-dashed p-5 text-center">
            <p className="font-medium">WAIT · NO VALIDATED LEVELS</p>
            <p className="mt-1 text-xs text-muted-foreground">
              No completed BSE {mode.toLowerCase()} plan exists for the current India market date.
            </p>
          </div>
        )}

        <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <ShieldCheck className="h-3.5 w-3.5" /> Advisory only · broker order execution OFF
        </div>
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const [now, setNow] = useState<Date | null>(null);
  const [quote, setQuote] = useState<QuoteState | null>(null);
  const [market, setMarket] = useState<MarketState | null>(null);
  const [plans, setPlans] = useState<{ INTRADAY: ModePlan | null; SWING: ModePlan | null }>({
    INTRADAY: null,
    SWING: null,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const indiaDate = useMemo(() => (now ? getIndiaMarketDate(now) : ""), [now]);
  const greeting = now ? getIndiaMarketGreeting(now) : "Trade Brain";
  const dayContext = now
    ? getIndiaMarketDayContext(now)
    : "Indian market context is calculated in Asia/Kolkata (IST).";

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const currentIndiaDate = getIndiaMarketDate(new Date());
      const [quoteResult, marketResult, historyResult]: any[] = await Promise.all([
        getQuote(BSE_TICKER),
        getMarketStatus(),
        getAnalysisHistory(30),
      ]);

      setQuote(quoteResult || null);
      setMarket(marketResult || null);

      const historyRows: any[] = Array.isArray(historyResult) ? historyResult : historyResult?.items || [];
      const candidates = historyRows
        .filter((row) => row?.trade_date === currentIndiaDate)
        .filter((row) => String(row?.ticker || "").toUpperCase().startsWith("BSE"))
        .slice(0, 12);

      const details = await Promise.all(
        candidates.map(async (row) => {
          try {
            return await getAnalysisResult(row.task_id) as any;
          } catch {
            return null;
          }
        })
      );

      const next: { INTRADAY: ModePlan | null; SWING: ModePlan | null } = {
        INTRADAY: null,
        SWING: null,
      };

      for (const result of details) {
        if (!result?.tradebrain_advisory || !result?.task_id || !result?.trade_date) continue;
        const mode = strictMode(result.tradebrain_advisory);
        if ((mode === "INTRADAY" || mode === "SWING") && !next[mode]) {
          next[mode] = {
            taskId: result.task_id,
            tradeDate: result.trade_date,
            signal: result.research_label || result.signal || "WAIT",
            advisory: result.tradebrain_advisory,
          };
        }
      }
      setPlans(next);
    } catch (e: any) {
      setError(e?.message || "Could not load the BSE decision workspace.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setNow(new Date());
    const clock = window.setInterval(() => setNow(new Date()), 60_000);
    refresh();
    const dataRefresh = window.setInterval(refresh, 60_000);
    return () => {
      window.clearInterval(clock);
      window.clearInterval(dataRefresh);
    };
  }, []);

  const quoteDirectionUp = (quote?.change || 0) >= 0;
  const QuoteIcon = quoteDirectionUp ? TrendingUp : TrendingDown;
  const source = quote?.price_source || "SOURCE UNAVAILABLE";
  const session = humanize(market?.session || "UNKNOWN");

  return (
    <div className="p-6 space-y-5 max-w-7xl">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold">BSE Today</h1>
            <Badge variant="outline">NSE:BSE</Badge>
            {indiaDate && <Badge variant="outline">India date {indiaDate}</Badge>}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{greeting} · {dayContext}</p>
        </div>
        <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
          <RefreshCw className={`mr-2 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh BSE
        </Button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>
      )}

      <Card>
        <CardContent className="p-5">
          <div className="grid gap-4 lg:grid-cols-[1.25fr_1fr_1fr] lg:items-center">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">BSE Ltd</p>
              <div className="mt-1 flex flex-wrap items-baseline gap-3">
                <span className="text-4xl font-bold tabular-nums">{money(quote?.price)}</span>
                <span className={`flex items-center gap-1 text-sm font-medium ${quoteDirectionUp ? "text-green-600" : "text-red-600"}`}>
                  <QuoteIcon className="h-4 w-4" /> {money(quote?.change)} · {pct(quote?.change_percent)}
                </span>
              </div>
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                <Badge variant="outline">Open {money(quote?.open)}</Badge>
                <Badge variant="outline">High {money(quote?.high)}</Badge>
                <Badge variant="outline">Low {money(quote?.low)}</Badge>
                <Badge variant="outline">Prev {money(quote?.prev_close)}</Badge>
              </div>
            </div>

            <div className="rounded-lg border p-4">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Clock3 className="h-4 w-4" /> India market state
              </div>
              <p className="mt-1 text-lg font-semibold">{session}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {market?.is_trading_day === false ? "Not an active trading session" : "NSE/BSE timing is always evaluated in IST"}
              </p>
            </div>

            <div className="rounded-lg border p-4">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Database className="h-4 w-4" /> Price provenance
              </div>
              <p className="mt-1 break-words text-sm font-semibold">{source}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {quote?.fallback_used ? `Fallback active${quote?.fallback_reason ? ` · ${quote.fallback_reason}` : ""}` : "Kite-primary path when authenticated/available"}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <div>
        <div className="mb-3 flex items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">BSE decision levels</h2>
            <p className="text-xs text-muted-foreground">
              Latest completed BSE plans from the current India market date. Each mode stands on its own evidence.
            </p>
          </div>
          <Link href="/analysis">
            <Button size="sm">
              Analyze BSE <ArrowRight className="ml-2 h-3.5 w-3.5" />
            </Button>
          </Link>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <ModeDecisionCard mode="INTRADAY" plan={plans.INTRADAY} />
          <ModeDecisionCard mode="SWING" plan={plans.SWING} />
        </div>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Activity className="h-4 w-4" /> Broader market context
            <Badge variant="outline">CONTEXT ONLY</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">NIFTY 50</p>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="font-semibold tabular-nums">{market?.nifty?.price?.toLocaleString("en-IN") || "—"}</span>
                <span className={(market?.nifty?.change || 0) >= 0 ? "text-xs text-green-600" : "text-xs text-red-600"}>
                  {pct(market?.nifty?.change_percent)}
                </span>
              </div>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">BANK NIFTY</p>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="font-semibold tabular-nums">{market?.banknifty?.price?.toLocaleString("en-IN") || "—"}</span>
                <span className={(market?.banknifty?.change || 0) >= 0 ? "text-xs text-green-600" : "text-xs text-red-600"}>
                  {pct(market?.banknifty?.change_percent)}
                </span>
              </div>
            </div>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            These indices are never Trade Brain trade targets. They are supporting context that may strengthen, weaken or leave a BSE Ltd thesis unchanged.
          </p>
        </CardContent>
      </Card>

      <div className="flex items-center justify-between rounded-lg border bg-muted/20 p-4 text-sm">
        <div>
          <p className="font-medium">No generic stock discovery on this branch.</p>
          <p className="text-xs text-muted-foreground">Trade Brain analyzes BSE Ltd; other market data exists only to improve the BSE decision.</p>
        </div>
        <div className="flex gap-2">
          <Link href="/charts"><Button variant="outline" size="sm">BSE Price & Structure</Button></Link>
          <Link href="/insights"><Button variant="outline" size="sm">BSE Evidence</Button></Link>
        </div>
      </div>
    </div>
  );
}
