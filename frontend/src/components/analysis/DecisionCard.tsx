"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TrendingUp, TrendingDown, Minus, AlertTriangle, ShieldCheck } from "lucide-react";
import type { TradeBrainAdvisory } from "@/lib/types";

const signalConfig: Record<string, { color: string; bg: string; icon: any }> = {
  LONG_CANDIDATE: { color: "text-green-700", bg: "bg-green-50 border-green-200", icon: TrendingUp },
  SHORT_CANDIDATE: { color: "text-red-700", bg: "bg-red-50 border-red-200", icon: TrendingDown },
  EXIT_CANDIDATE: { color: "text-amber-700", bg: "bg-amber-50 border-amber-200", icon: AlertTriangle },
  WAIT: { color: "text-yellow-700", bg: "bg-yellow-50 border-yellow-200", icon: Minus },
  NO_TRADE: { color: "text-slate-700", bg: "bg-slate-50 border-slate-200", icon: Minus },
  BUY: { color: "text-green-700", bg: "bg-green-50 border-green-200", icon: TrendingUp },
  "STRONG BUY": { color: "text-green-700", bg: "bg-green-50 border-green-200", icon: TrendingUp },
  OVERWEIGHT: { color: "text-green-700", bg: "bg-green-50 border-green-200", icon: TrendingUp },
  HOLD: { color: "text-yellow-700", bg: "bg-yellow-50 border-yellow-200", icon: Minus },
  SELL: { color: "text-red-700", bg: "bg-red-50 border-red-200", icon: TrendingDown },
  SHORT: { color: "text-red-700", bg: "bg-red-50 border-red-200", icon: AlertTriangle },
  UNDERWEIGHT: { color: "text-red-700", bg: "bg-red-50 border-red-200", icon: TrendingDown },
};

interface Props {
  signal: string | null;
  ticker: string;
  duration?: number | null;
  advisory?: TradeBrainAdvisory | null;
}

function humanize(value?: string | null) {
  return value ? value.replaceAll("_", " ") : null;
}

function textValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatPrice(value: number | null) {
  return value === null
    ? "—"
    : `₹${value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function DecisionCard({ signal, ticker, duration, advisory }: Props) {
  if (!signal) return null;

  const config = signalConfig[signal] || signalConfig.NO_TRADE;
  const Icon = config.icon;
  const finalStatus = humanize(advisory?.final_status);
  const blocked = Boolean(advisory?.final_status?.startsWith("BLOCK"));
  const parsed = advisory?.ai_candidate || {};
  const geometry = advisory?.trade_geometry;
  const mode = geometry?.mode || textValue(parsed.mode);
  const direction = geometry?.direction || textValue(parsed.direction);
  const entry = geometry?.entry ?? numberValue(parsed.entry);
  const stopLoss = geometry?.stop_loss ?? numberValue(parsed.stop_loss);
  const target = geometry?.take_profit ?? numberValue(parsed.take_profit);
  const rewardRisk = geometry?.gross_reward_risk ?? advisory?.gate?.reward_risk ?? null;
  const hasLevels = entry !== null || stopLoss !== null || target !== null;

  return (
    <Card className={`${config.bg} border`}>
      <CardContent className="p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="rounded-full border bg-background/70 p-2">
              <Icon className={`h-5 w-5 ${config.color}`} />
            </div>
            <div>
              <p className="text-[11px] text-muted-foreground">{ticker === "BSE" ? "BSE Ltd · NSE:BSE" : ticker}</p>
              <div className="flex flex-wrap items-center gap-2">
                <p className={`text-2xl font-bold ${config.color}`}>{humanize(signal)}</p>
                {mode && <Badge variant="outline">{mode}</Badge>}
                {direction && <Badge variant="outline">{direction}</Badge>}
              </div>
            </div>
          </div>
          {duration ? <span className="text-xs text-muted-foreground">{Math.round(duration)}s</span> : null}
        </div>

        {hasLevels ? (
          <div className="grid grid-cols-3 gap-2">
            <div className="rounded-md border bg-background/70 p-2">
              <p className="text-[10px] text-muted-foreground">ENTRY</p>
              <p className="font-semibold tabular-nums">{formatPrice(entry)}</p>
            </div>
            <div className="rounded-md border bg-background/70 p-2">
              <p className="text-[10px] text-muted-foreground">STOP</p>
              <p className="font-semibold tabular-nums">{formatPrice(stopLoss)}</p>
            </div>
            <div className="rounded-md border bg-background/70 p-2">
              <p className="text-[10px] text-muted-foreground">TARGET</p>
              <p className="font-semibold tabular-nums">{formatPrice(target)}</p>
            </div>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            No valid entry / stop / target geometry. Trade Brain will not invent levels.
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t pt-2">
          <Badge variant="outline" className={blocked ? "border-red-300 text-red-700" : "border-slate-300"}>
            {finalStatus || "RESEARCH ONLY"}
          </Badge>
          {rewardRisk != null && <Badge variant="outline">R:R {rewardRisk.toFixed(2)}:1</Badge>}
          <Badge variant="outline" className="border-slate-300 text-slate-700">
            <ShieldCheck className="h-3 w-3 mr-1" /> No order authorization
          </Badge>
        </div>

        {advisory?.reason && <p className="text-xs text-muted-foreground">{advisory.reason}</p>}
        {advisory?.gate?.hard_rule_failures?.length ? (
          <div className="rounded-md border border-red-200 bg-red-50/60 p-2 text-xs text-red-700">
            <span className="font-semibold">Blocked by: </span>
            {advisory.gate.hard_rule_failures.join(" · ")}
          </div>
        ) : null}
        {advisory?.gate?.warnings?.length ? (
          <div className="text-xs text-amber-700">
            <span className="font-semibold">Warnings: </span>
            {advisory.gate.warnings.join(" · ")}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
