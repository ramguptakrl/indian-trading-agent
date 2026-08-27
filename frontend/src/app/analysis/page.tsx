"use client";

import { useEffect, useState } from "react";
import {
  useHorizonAnalysisStore,
  type HorizonPlanState,
} from "@/lib/horizon-analysis-store";
import { getIndiaMarketDate } from "@/lib/market-time";
import { DecisionCard } from "@/components/analysis/DecisionCard";
import { ReportPanel } from "@/components/analysis/ReportPanel";
import { DebateView } from "@/components/analysis/DebateView";
import { AnalysisOptions } from "@/components/analysis/AnalysisOptions";
import { StatsCard } from "@/components/analysis/StatsCard";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loader2, Play, RotateCcw, Calculator } from "lucide-react";
import { PositionSizeCalculator } from "@/components/PositionSizeCalculator";

const BSE_TICKER = "BSE";
const SHARED_REPORT_BY_ANALYST: Record<string, string> = {
  market: "market_report",
  social: "sentiment_report",
  news: "news_report",
  fundamentals: "fundamentals_report",
};
const SHARED_REPORT_KEYS = Object.values(SHARED_REPORT_BY_ANALYST);
const DECISION_REPORT_KEYS = ["investment_plan", "trader_investment_plan", "final_trade_decision"];
const ANALYST_LABELS: Record<string, string> = {
  market: "Market",
  social: "Social",
  news: "News",
  fundamentals: "Fundamentals",
};

function pickReports(reports: Record<string, string>, keys: string[]) {
  return keys.reduce<Record<string, string>>((selected, key) => {
    if (reports[key]) selected[key] = reports[key];
    return selected;
  }, {});
}

function sharedResearchState(
  intraday: HorizonPlanState,
  swing: HorizonPlanState,
  selectedAnalysts: string[],
) {
  const sourceReports = Object.keys(intraday.reports).length ? intraday.reports : swing.reports;
  const sharedReports = pickReports(sourceReports, SHARED_REPORT_KEYS);
  const complete = selectedAnalysts.every((analyst) => {
    const key = SHARED_REPORT_BY_ANALYST[analyst];
    return !key || Boolean(sharedReports[key]);
  });
  const error = !complete ? (intraday.error || swing.error) : null;
  return { sharedReports, complete, error };
}

function SharedResearchSummary({
  intraday,
  swing,
  selectedAnalysts,
}: {
  intraday: HorizonPlanState;
  swing: HorizonPlanState;
  selectedAnalysts: string[];
}) {
  if (intraday.status === "idle" && swing.status === "idle") return null;

  const { sharedReports, complete: sharedComplete, error: sharedError } = sharedResearchState(
    intraday,
    swing,
    selectedAnalysts,
  );
  const sharedFailed = !sharedComplete && Boolean(sharedError);
  const sharedStatus = sharedFailed ? "STOPPED" : sharedComplete ? "READY" : "BUILDING";

  return (
    <Card>
      <CardContent className="p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-semibold">1. Shared evidence</h2>
              <Badge variant="outline">PULLED ONCE</Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              One evidence pack is reused by both horizons. It is not a trade verdict.
            </p>
          </div>
          <Badge variant={sharedFailed ? "destructive" : "secondary"}>{sharedStatus}</Badge>
        </div>

        <div className="flex flex-wrap gap-2">
          {selectedAnalysts.map((analyst) => {
            const reportKey = SHARED_REPORT_BY_ANALYST[analyst];
            const done = !reportKey || Boolean(sharedReports[reportKey]);
            return (
              <Badge key={analyst} variant="outline" className={done ? "border-green-300 text-green-700" : ""}>
                {done ? "✓" : "…"} {ANALYST_LABELS[analyst] || analyst}
              </Badge>
            );
          })}
        </div>

        {!sharedComplete && !sharedFailed && (
          <div className="flex items-center gap-2 text-xs text-blue-700">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Building shared evidence once. The second horizon waits for this same pack.
          </div>
        )}

        {sharedFailed && (
          <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-700">
            Shared research stopped before completion{sharedError ? `: ${sharedError}` : "."}
          </div>
        )}

        {Object.keys(sharedReports).length > 0 && (
          <details className="rounded-md border bg-muted/10">
            <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium">
              View Market / News / Fundamentals evidence
            </summary>
            <div className="border-t p-3">
              <ReportPanel reports={sharedReports} />
            </div>
          </details>
        )}
      </CardContent>
    </Card>
  );
}

function HorizonSummary({
  plan,
  title,
  description,
  step,
  sharedFailure,
}: {
  plan: HorizonPlanState;
  title: string;
  description: string;
  step: number;
  sharedFailure?: string | null;
}) {
  const blockedByShared = Boolean(
    sharedFailure && plan.status === "error" && plan.error === sharedFailure && !plan.signal,
  );
  const decisionReports = pickReports(plan.reports, DECISION_REPORT_KEYS);
  const hasDebate = Boolean(
    plan.debates.bull ||
    plan.debates.bear ||
    plan.riskDebates.aggressive ||
    plan.riskDebates.conservative ||
    plan.riskDebates.neutral
  );
  const hasDiagnostics = !blockedByShared && Boolean(
    plan.taskId || plan.stats || Object.keys(decisionReports).length || hasDebate
  );

  return (
    <Card className="h-full">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-semibold">{step}. {title}</h2>
              <Badge variant="outline">{plan.mode}</Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-1">{description}</p>
          </div>
          <Badge variant={plan.status === "error" && !blockedByShared ? "destructive" : "secondary"}>
            {blockedByShared ? "NOT RUN" : plan.status.toUpperCase()}
          </Badge>
        </div>

        {plan.error && !blockedByShared && (
          <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-700">
            {plan.error}
          </div>
        )}

        {blockedByShared && (
          <div className="rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">
            Not run — shared evidence was unavailable. See the single error above.
          </div>
        )}

        {plan.status === "running" && (
          <div className="flex items-center gap-2 rounded-md border border-blue-200 bg-blue-50/50 p-3 text-xs text-blue-700">
            <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
            <span>{plan.heartbeat || "Working on this horizon..."}</span>
          </div>
        )}

        {plan.signal ? (
          <DecisionCard
            signal={plan.signal}
            ticker={BSE_TICKER}
            duration={plan.duration}
            advisory={plan.tradebrainAdvisory}
          />
        ) : plan.status === "completed" ? (
          <div className="rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">
            Completed with no publishable setup — WAIT / NO TRADE.
          </div>
        ) : null}

        {hasDiagnostics && (
          <details className="rounded-md border bg-muted/10">
            <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium">
              Agent reasoning & diagnostics
            </summary>
            <div className="border-t p-3 space-y-4">
              {plan.taskId && (
                <p className="text-[10px] text-muted-foreground font-mono">Task: {plan.taskId}</p>
              )}
              {Object.keys(decisionReports).length > 0 && <ReportPanel reports={decisionReports} />}
              {hasDebate && (
                <DebateView
                  bull={plan.debates.bull}
                  bear={plan.debates.bear}
                  riskAggressive={plan.riskDebates.aggressive}
                  riskConservative={plan.riskDebates.conservative}
                  riskNeutral={plan.riskDebates.neutral}
                />
              )}
              {plan.stats && plan.status === "completed" && (
                <StatsCard stats={plan.stats} duration={plan.duration} />
              )}
            </div>
          </details>
        )}
      </CardContent>
    </Card>
  );
}

export default function AnalysisPage() {
  const analysis = useHorizonAnalysisStore();
  const [tradeDateInput, setTradeDateInput] = useState(analysis.tradeDate || "");
  const [indiaToday, setIndiaToday] = useState("");
  const [selectedAnalysts, setSelectedAnalysts] = useState<string[]>([
    "market", "news", "fundamentals",
  ]);
  const [depth, setDepth] = useState(1);
  const [language, setLanguage] = useState("English");
  const [calcOpen, setCalcOpen] = useState(false);

  useEffect(() => {
    const refreshIndiaDate = () => {
      const istDate = getIndiaMarketDate();
      setIndiaToday(istDate);
      setTradeDateInput((current) => current || analysis.tradeDate || istDate);
    };

    refreshIndiaDate();
    const timer = window.setInterval(refreshIndiaDate, 60_000);
    return () => window.clearInterval(timer);
  }, [analysis.tradeDate]);

  const handleRun = () => {
    if (!tradeDateInput) return;
    analysis.start(tradeDateInput, {
      analysts: selectedAnalysts,
      max_debate_rounds: depth,
      max_risk_discuss_rounds: depth,
      output_language: language,
    });
  };

  const intraday = analysis.plans.INTRADAY;
  const swing = analysis.plans.SWING;
  const running = analysis.status === "running";
  const hasRun = analysis.status !== "idle";
  const sharedFailure = sharedResearchState(intraday, swing, selectedAnalysts).error;

  return (
    <div className="p-6 space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-bold">BSE Analysis</h1>
            <Badge variant="outline">BSE Ltd · NSE:BSE</Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Shared evidence first, then separate INTRADAY and SWING · MTF decisions.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setCalcOpen(true)}>
            <Calculator className="h-3.5 w-3.5 mr-2" /> Position Calc
          </Button>
          {hasRun && (
            <Button variant="outline" size="sm" onClick={analysis.reset}>
              <RotateCcw className="h-3.5 w-3.5 mr-2" /> New Analysis
            </Button>
          )}
        </div>
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-end">
            <div className="w-full md:w-60">
              <label className="text-xs text-muted-foreground mb-1 block">
                Analysis date <span className="font-semibold text-foreground">(India / IST)</span>
              </label>
              <Input
                type="date"
                value={tradeDateInput}
                max={indiaToday || undefined}
                onChange={(e) => setTradeDateInput(e.target.value)}
                disabled={running}
              />
              {indiaToday && (
                <p className="mt-1 text-[10px] text-muted-foreground">India market date: {indiaToday}</p>
              )}
            </div>
            <Button onClick={handleRun} disabled={running || !tradeDateInput} className="md:min-w-60">
              {running ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" /> Analyzing BSE...
                </>
              ) : (
                <>
                  <Play className="h-4 w-4 mr-2" /> Analyze INTRADAY + SWING
                </>
              )}
            </Button>
            <div className="text-xs text-muted-foreground md:ml-auto md:text-right">
              <div>INTRADAY: LONG/SHORT · same session</div>
              <div>SWING: LONG only · Zerodha MTF</div>
            </div>
          </div>
        </CardContent>
      </Card>

      <details className="rounded-lg border bg-muted/10">
        <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium">
          Advanced analysis settings
        </summary>
        <div className="border-t p-4">
          <AnalysisOptions
            analysts={selectedAnalysts}
            onAnalystsChange={setSelectedAnalysts}
            depth={depth}
            onDepthChange={setDepth}
            language={language}
            onLanguageChange={setLanguage}
            disabled={running}
          />
        </div>
      </details>

      {analysis.error && (
        <Card className="border-red-500/30 bg-red-500/5">
          <CardContent className="p-4 text-sm text-red-700">{analysis.error}</CardContent>
        </Card>
      )}

      <SharedResearchSummary
        intraday={intraday}
        swing={swing}
        selectedAnalysts={selectedAnalysts}
      />

      {hasRun && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <HorizonSummary
            plan={intraday}
            step={2}
            title="INTRADAY"
            description="Same-session LONG/SHORT only. After the cutoff, the correct result is NO TRADE."
            sharedFailure={sharedFailure}
          />
          <HorizonSummary
            plan={swing}
            step={3}
            title="SWING · MTF"
            description="Multi-day LONG only. Missing MTF eligibility/funding stays WAIT / NO TRADE."
            sharedFailure={sharedFailure}
          />
        </div>
      )}

      <div className="text-[11px] text-muted-foreground">
        Advisory research only · trade authorization OFF · order execution OFF.
      </div>

      <PositionSizeCalculator
        open={calcOpen}
        onClose={() => setCalcOpen(false)}
        ticker={BSE_TICKER}
      />
    </div>
  );
}
