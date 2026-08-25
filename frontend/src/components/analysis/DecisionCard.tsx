"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
  ShieldCheck,
  Crosshair,
  OctagonMinus,
  Target,
} from "lucide-react";
import type { TradeBrainAdvisory } from "@/lib/types";

const signalConfig: Record<string, { color: string; bg: string; icon: any }> = {
  LONG_CANDIDATE: { color: "text-green-700", bg: "bg-green-50 border-green-200", icon: TrendingUp },
  SHORT_CANDIDATE: { color: "text-red-700", bg: "bg-red-50 border-red-200", icon: TrendingDown },
  EXIT_CANDIDATE: { color: "text-amber-700", bg: "bg-amber-50 border-amber-200", icon: AlertTriangle },
  WAIT: { color: "text-yellow-700", bg: "bg-yellow-50 border-yellow-200", icon: Minus },
  NO_TRADE: { color: "text-slate-700", bg: "bg-slate-50 border-slate-200", icon: Minus },
  // Historical/upstream compatibility only.
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

function LevelBox({ label, value, icon: Icon }: { label: string; value: number | null; icon: any }) {
  return (
    <div className="rounded-lg border bg-background/80 p-3">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <p className="mt-1 text-lg font-semibold tabular-nums">{formatPrice(value)}</p>
    </div>
  );
}

export function DecisionCard({ signal, ticker, duration, advisory }: Props) {
  if (!signal) return null;

  const config = signalConfig[signal] || signalConfig.NO_TRADE;
  const Icon = config.icon;
  const finalStatus = humanize(advisory?.final_status);
  const blocked = Boolean(advisory?.final_status?.startsWith("BLOCK"));
  const calendarVerified = advisory?.calendar?.calendar_verified;
  const parsed = advisory?.ai_candidate || {};
  const geometry = advisory?.trade_geometry;

  // Prefer deterministic-gate geometry. If the gate stopped earlier (for example because
  // the market is closed), display only the strict labelled parser fields as research
  // levels. No free-form prose is converted into prices here.
  const mode = geometry?.mode || textValue(parsed.mode);
  const direction = geometry?.direction || textValue(parsed.direction);
  const entry = geometry?.entry ?? numberValue(parsed.entry);
  const stopLoss = geometry?.stop_loss ?? numberValue(parsed.stop_loss);
  const primaryTarget = geometry?.take_profit ?? numberValue(parsed.take_profit);
  const rewardRisk = geometry?.gross_reward_risk ?? advisory?.gate?.reward_risk ?? null;
  const hasLevels = entry !== null || stopLoss !== null || primaryTarget !== null;
  const gatePassed = advisory?.final_status === "ADVISORY_CANDIDATE_PASS";

  return (
    <Card className={`${config.bg} border-2`}>
      <CardContent className="p-6 space-y-5">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className={`p-3 rounded-full ${config.bg}`}>
              <Icon className={`h-8 w-8 ${config.color}`} />
            </div>
            <div>
              <p className="text-sm text-muted-foreground">BSE Ltd · NSE:BSE</p>
              <div className="flex flex-wrap items-center gap-2">
                <p className={`text-3xl font-bold ${config.color}`}>{humanize(signal)}</p>
                {mode && <Badge variant="outline">{mode}</Badge>}
                {direction && <Badge variant="outline">{direction}</Badge>}
              </div>
            </div>
          </div>
          {duration && (
            <div className="text-right">
              <p className="text-xs text-muted-foreground">Analysis Duration</p>
              <p className="text-lg font-sans">{Math.round(duration)}s</p>
            </div>
          )}
        </div>

        {hasLevels && (
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {gatePassed ? "Trade Brain price geometry" : "Strictly parsed research levels"}
              </p>
              {!gatePassed && (
                <Badge variant="outline" className="border-amber-300 text-amber-700">
                  Not a live authorization
                </Badge>
              )}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <LevelBox label="Entry" value={entry} icon={Crosshair} />
              <LevelBox label="Stop-Loss" value={stopLoss} icon={OctagonMinus} />
              <LevelBox label="Primary Target" value={primaryTarget} icon={Target} />
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              <Badge variant="outline">
                Gross R:R {rewardRisk === null ? "—" : `${rewardRisk.toFixed(2)}:1`}
              </Badge>
              {advisory?.costs?.net_reward_risk != null && (
                <Badge variant="outline">
                  Net modeled R:R {advisory.costs.net_reward_risk.toFixed(2)}:1
                </Badge>
              )}
            </div>
          </div>
        )}

        {!hasLevels && (signal === "WAIT" || signal === "NO_TRADE" || blocked) && (
          <div className="rounded-lg border bg-background/70 p-3 text-sm text-muted-foreground">
            No valid BSE entry/stop/target geometry is available for this result. Trade Brain will not invent levels.
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t pt-3">
          <Badge variant="outline" className={blocked ? "border-red-300 text-red-700" : "border-slate-300"}>
            {finalStatus || "RESEARCH CANDIDATE — FINAL GATE NOT AVAILABLE"}
          </Badge>
          {calendarVerified !== undefined && (
            <Badge variant="outline" className={calendarVerified ? "border-green-300 text-green-700" : "border-red-300 text-red-700"}>
              Calendar {calendarVerified ? "verified" : "unverified"}
            </Badge>
          )}
          <Badge variant="outline" className="border-slate-300 text-slate-700">
            <ShieldCheck className="h-3 w-3 mr-1" /> Advisory only
          </Badge>
          <Badge variant="outline" className="border-slate-300 text-slate-700">
            No order authorization
          </Badge>
        </div>

        {advisory?.reason && (
          <p className="text-xs text-muted-foreground">{advisory.reason}</p>
        )}
        {advisory?.gate?.hard_rule_failures?.length ? (
          <div className="text-xs text-red-700">
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
