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

export function DecisionCard({ signal, ticker, duration, advisory }: Props) {
  if (!signal) return null;

  const config = signalConfig[signal] || signalConfig.NO_TRADE;
  const Icon = config.icon;
  const finalStatus = humanize(advisory?.final_status);
  const blocked = Boolean(advisory?.final_status?.startsWith("BLOCK"));
  const calendarVerified = advisory?.calendar?.calendar_verified;

  return (
    <Card className={`${config.bg} border-2`}>
      <CardContent className="p-6 space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className={`p-3 rounded-full ${config.bg}`}>
              <Icon className={`h-8 w-8 ${config.color}`} />
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Trade Brain research label for {ticker}</p>
              <p className={`text-3xl font-bold ${config.color}`}>{humanize(signal)}</p>
            </div>
          </div>
          {duration && (
            <div className="text-right">
              <p className="text-xs text-muted-foreground">Analysis Duration</p>
              <p className="text-lg font-sans">{Math.round(duration)}s</p>
            </div>
          )}
        </div>

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
      </CardContent>
    </Card>
  );
}
