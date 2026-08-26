"use client";

import { useEffect, useState } from "react";
import {
  useHorizonAnalysisStore,
  type HorizonPlanState,
} from "@/lib/horizon-analysis-store";
import { getIndiaMarketDate } from "@/lib/market-time";
import { DecisionCard } from "@/components/analysis/DecisionCard";
import { AgentProgress } from "@/components/analysis/AgentProgress";
import { ReportPanel } from "@/components/analysis/ReportPanel";
import { DebateView } from "@/components/analysis/DebateView";
import { AnalysisOptions } from "@/components/analysis/AnalysisOptions";
import { StatsCard } from "@/components/analysis/StatsCard";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { HelpSection } from "@/components/HelpSection";
import { analysisHelp } from "@/lib/help-content";
import { Loader2, Play, RotateCcw, History, Calculator, Building2 } from "lucide-react";
import { NextStep } from "@/components/NextStep";
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

function pickReports(reports: Record<string, string>, keys: string[]) {
  return keys.reduce<Record<string, string>>((selected, key) => {
    if (reports[key]) selected[key] = reports[key];
    return selected;
  }, {});
}

function HorizonSummary({
  plan,
  title,
  description,
}: {
  plan: HorizonPlanState;
  title: string;
  description: string;
}) {
  return (
    <Card className="h-full">
      <CardContent className="p-5 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold">{title}</h2>
              <Badge variant="outline">{plan.mode}</Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-1">{description}</p>
          </div>
          <Badge variant={plan.status === "error" ? "destructive" : "secondary"}>
            {plan.status.toUpperCase()}
          </Badge>
        </div>

        {plan.taskId && (
          <p className="text-[10px] text-muted-foreground font-mono">Task: {plan.taskId}</p>
        )}

        {plan.error && (
          <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-700">
            {plan.error}
          </div>
        )}

        {plan.status === "running" && plan.heartbeat && (
          <div className="rounded-md border border-blue-200 bg-blue-50/50 p-3">
            <div className="flex items-center gap-2 text-sm">
              <Loader2 className="h-3 w-3 animate-spin text-blue-500" />
              <span className="text-blue-700 font-mono text-xs truncate flex-1">{plan.heartbeat}</span>
            </div>
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
            This horizon completed without a trade candidate. Treat it as WAIT / NO TRADE.
          </div>
        ) : null}

        {plan.stats && plan.status === "completed" && (
          <StatsCard stats={plan.stats} duration={plan.duration} />
        )}
      </CardContent>
    </Card>
  );
}

function SharedResearchTrail({
  intraday,
  swing,
  selectedAnalysts,
}: {
  intraday: HorizonPlanState;
  swing: HorizonPlanState;
  selectedAnalysts: string[];
}) {
  if (intraday.status === "idle" && swing.status === "idle") return null;

  const sourceReports = Object.keys(intraday.reports).length ? intraday.reports : swing.reports;
  const sharedReports = pickReports(sourceReports, SHARED_REPORT_KEYS);
  const sharedComplete = selectedAnalysts.every((analyst) => {
    const key = SHARED_REPORT_BY_ANALYST[analyst];
    return !key || Boolean(sharedReports[key]);
  });
  const sharedStatus = sharedComplete ? "completed" : "running";

  return (
    <Card>
      <CardContent className="p-5 space-y-5">
        <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-semibold">Shared BSE research</h3>
              <Badge variant="outline">PULLED ONCE</Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Market, social, news and fundamentals research is gathered once into one audited BSE evidence pack, then reused unchanged by both horizon decision pipelines.
            </p>
          </div>
          <p className="text-[11px] text-muted-foreground max-w-md">
            Same evidence does not mean same verdict: INTRADAY and SWING · MTF still run separate Bull/Bear research, Trader, risk debate and Portfolio Manager decisions.
          </p>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          <div className="lg:col-span-1">
            <AgentProgress
              reports={sharedReports}
              signal={null}
              status={sharedStatus}
              pipeline="shared"
              selectedAnalysts={selectedAnalysts}
            />
          </div>
          <div className="lg:col-span-3">
            <ReportPanel reports={sharedReports} />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function HorizonResearchTrail({ plan, title }: { plan: HorizonPlanState; title: string }) {
  if (plan.status === "idle") return null;

  const decisionReports = pickReports(plan.reports, DECISION_REPORT_KEYS);
  const progressReports = {
    ...decisionReports,
    bull_history: plan.debates.bull,
    bear_history: plan.debates.bear,
    risk_aggressive_history: plan.riskDebates.aggressive,
    risk_conservative_history: plan.riskDebates.conservative,
    risk_neutral_history: plan.riskDebates.neutral,
  };

  return (
    <Card>
      <CardContent className="p-5 space-y-5">
        <div>
          <h3 className="font-semibold">{title} decision trail</h3>
          <p className="text-xs text-muted-foreground">
            Independent horizon reasoning using the shared analyst evidence above. Bull/Bear debate, Research Manager, Trader, risk debate and Portfolio Manager remain separate for this horizon.
          </p>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          <div className="lg:col-span-1">
            <AgentProgress
              reports={progressReports}
              signal={plan.signal}
              status={plan.status}
              pipeline="decision"
            />
          </div>
          <div className="lg:col-span-3 space-y-4">
            <ReportPanel reports={decisionReports} />
            <DebateView
              bull={plan.debates.bull}
              bear={plan.debates.bear}
              riskAggressive={plan.riskDebates.aggressive}
              riskConservative={plan.riskDebates.conservative}
              riskNeutral={plan.riskDebates.neutral}
            />
          </div>
        </div>
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

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold">BSE Ltd Analysis</h1>
            <Badge variant="outline">NSE:BSE</Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            One shared BSE research pass feeds two independent decisions: INTRADAY and SWING · MTF. Neither horizon may substitute for the other.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setCalcOpen(true)}>
            <Calculator className="h-3 w-3 mr-2" />
            Position Calc
          </Button>
          {hasRun && (
            <Button variant="outline" size="sm" onClick={analysis.reset}>
              <RotateCcw className="h-3 w-3 mr-2" />
              New Analysis
            </Button>
          )}
        </div>
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col lg:flex-row gap-4 lg:items-end">
            <div className="flex-1 rounded-lg border bg-muted/20 px-4 py-3">
              <div className="flex items-center gap-3">
                <Building2 className="h-5 w-5 text-green-600" />
                <div>
                  <p className="text-xs text-muted-foreground">Fixed Trade Brain instrument</p>
                  <p className="font-semibold">BSE Ltd · NSE:BSE</p>
                  <p className="text-[11px] text-muted-foreground">ISIN INE118H01025 · only tradable target</p>
                </div>
              </div>
            </div>

            <div className="w-full lg:w-56">
              <label className="text-xs text-muted-foreground mb-1 block">
                Analysis Date <span className="font-semibold text-foreground">(India / IST)</span>
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

            <Button onClick={handleRun} disabled={running || !tradeDateInput} className="h-10">
              {running ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Research once · decide twice...
                </>
              ) : (
                <>
                  <Play className="h-4 w-4 mr-2" />
                  Analyze INTRADAY + SWING
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="rounded-lg border px-4 py-3">
          <p className="font-semibold text-sm">INTRADAY</p>
          <p className="text-xs text-muted-foreground">Independent LONG or SHORT setup · same session · flat before 15:15 IST.</p>
        </div>
        <div className="rounded-lg border px-4 py-3">
          <p className="font-semibold text-sm">SWING · ZERODHA MTF</p>
          <p className="text-xs text-muted-foreground">Independent LONG-only multi-day setup · MTF eligibility/funding/costs must be verified.</p>
        </div>
      </div>

      <AnalysisOptions
        analysts={selectedAnalysts}
        onAnalystsChange={setSelectedAnalysts}
        depth={depth}
        onDepthChange={setDepth}
        language={language}
        onLanguageChange={setLanguage}
        disabled={running}
      />

      {analysis.error && (
        <Card className="border-red-500/30 bg-red-500/5">
          <CardContent className="p-4 text-red-700">{analysis.error}</CardContent>
        </Card>
      )}

      <SharedResearchTrail
        intraday={intraday}
        swing={swing}
        selectedAnalysts={selectedAnalysts}
      />

      {hasRun && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <HorizonSummary
            plan={intraday}
            title="INTRADAY plan"
            description="Same-session LONG/SHORT decision. Weak evidence becomes WAIT / NO TRADE, never a SWING substitute."
          />
          <HorizonSummary
            plan={swing}
            title="SWING · MTF plan"
            description="Multi-day LONG-only decision. Weak evidence becomes WAIT / NO TRADE, never an INTRADAY substitute."
          />
        </div>
      )}

      <HorizonResearchTrail plan={intraday} title="INTRADAY" />
      <HorizonResearchTrail plan={swing} title="SWING · MTF" />

      {analysis.status === "completed" && (intraday.signal || swing.signal) && (
        <NextStep
          title="Review BSE evidence or log what you actually did"
          description="Both plans are advisory research, not broker orders. If you independently act, record the real fill in Actual Trades."
          href="/history"
          buttonText="BSE Analysis Outcomes"
          icon={History}
        />
      )}

      <HelpSection title="How BSE Analysis Works" items={analysisHelp} />

      <PositionSizeCalculator
        open={calcOpen}
        onClose={() => setCalcOpen(false)}
        ticker={BSE_TICKER}
      />
    </div>
  );
}
