"use client";

import { useEffect, useState } from "react";
import {
  buildBseEvidenceBaseline,
  getBseActualTradeStats,
  getBseChallengerStats,
  getBseEvidenceBaseline,
  getBseEvidenceDoctrine,
  getBseFocusLabStats,
  getBseProspectiveGapObservations,
} from "@/lib/bse-api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  AlertTriangle,
  BarChart3,
  Brain,
  CheckCircle2,
  Database,
  FlaskConical,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";

function metric(value: unknown, suffix = "") {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return `${value.toLocaleString("en-IN")}${suffix}`;
  return `${String(value)}${suffix}`;
}

function Readiness({ label, ready }: { label: string; ready?: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-lg border p-3">
      <span className="text-sm">{label}</span>
      <Badge variant="outline" className={ready ? "border-green-300 text-green-700" : "border-amber-300 text-amber-700"}>
        {ready ? "READY" : "NOT READY"}
      </Badge>
    </div>
  );
}

export default function BseEvidencePage() {
  const [baseline, setBaseline] = useState<any>(null);
  const [prospective, setProspective] = useState<any>(null);
  const [focus, setFocus] = useState<any>(null);
  const [challengers, setChallengers] = useState<any>(null);
  const [actual, setActual] = useState<any>(null);
  const [doctrine, setDoctrine] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [building, setBuilding] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  const load = async () => {
    setLoading(true);
    setErrors([]);
    const jobs = await Promise.allSettled([
      getBseEvidenceBaseline(),
      getBseProspectiveGapObservations(),
      getBseFocusLabStats(),
      getBseChallengerStats(),
      getBseActualTradeStats(),
      getBseEvidenceDoctrine(),
    ]);

    const setters = [setBaseline, setProspective, setFocus, setChallengers, setActual, setDoctrine];
    const nextErrors: string[] = [];
    jobs.forEach((job, index) => {
      if (job.status === "fulfilled") setters[index](job.value);
      else {
        setters[index](null);
        nextErrors.push(job.reason?.message || "Evidence endpoint unavailable");
      }
    });
    setErrors(Array.from(new Set(nextErrors)));
    setLoading(false);
  };

  const buildBaseline = async () => {
    setBuilding(true);
    try {
      await buildBseEvidenceBaseline();
      await load();
    } catch (e: any) {
      setErrors((existing) => Array.from(new Set([...existing, e?.message || "Could not build BSE evidence baseline"])));
    } finally {
      setBuilding(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const report = baseline?.report || baseline;
  const coverage = report?.coverage || {};
  const daily = report?.daily || {};
  const intraday = report?.intraday || {};
  const readiness = report?.evidence_readiness || {};
  const quality = report?.data_quality || {};
  const observations = prospective?.observations || [];
  const scalarChallengerStats = Object.entries(challengers || {}).filter(
    ([, value]) => typeof value === "number" || typeof value === "string"
  );

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold flex items-center gap-2"><Brain className="h-6 w-6" /> BSE Evidence</h1>
            <Badge variant="outline">NSE:BSE</Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Audited descriptive evidence, replay outcomes and frozen prospective validation for BSE Ltd only.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={`mr-1 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
          </Button>
          <Button size="sm" onClick={buildBaseline} disabled={building}>
            <Database className="mr-1 h-3.5 w-3.5" /> {building ? "Building..." : "Build BSE Baseline"}
          </Button>
        </div>
      </div>

      <div className="flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50 p-3 text-xs text-blue-800">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
        <span>
          Evidence readiness is not profitability. This page cannot authorize a trade, promote a challenger automatically, or place a broker order.
        </span>
      </div>

      {errors.length > 0 && (
        <Card className="border-amber-200 bg-amber-50/40">
          <CardContent className="p-4">
            <div className="flex items-start gap-2 text-sm text-amber-800">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <p className="font-medium">Some evidence is not available yet.</p>
                <ul className="mt-1 list-disc pl-4 text-xs space-y-1">
                  {errors.map((item) => <li key={item}>{item}</li>)}
                </ul>
                <p className="mt-2 text-xs">That is expected on a fresh bootstrap; missing evidence is shown as missing rather than guessed.</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-4">
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Daily audited bars</p><p className="text-2xl font-bold">{metric(coverage.daily_bars)}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">5m audited bars</p><p className="text-2xl font-bold">{metric(coverage.intraday_bars)}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Full intraday sessions</p><p className="text-2xl font-bold">{metric(coverage.intraday_full_regular_sessions)}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Unresolved data issues</p><p className="text-2xl font-bold">{metric(quality.unresolved_issues)}</p></CardContent></Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-base flex items-center gap-2"><Database className="h-4 w-4" /> Descriptive BSE baseline</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div className="rounded-lg border p-3"><p className="text-xs text-muted-foreground">Median absolute opening gap</p><p className="font-semibold">{metric(daily.absolute_opening_gap_pct?.median, "%")}</p></div>
              <div className="rounded-lg border p-3"><p className="text-xs text-muted-foreground">90th percentile abs. gap</p><p className="font-semibold">{metric(daily.absolute_opening_gap_pct?.p90, "%")}</p></div>
              <div className="rounded-lg border p-3"><p className="text-xs text-muted-foreground">Median session range</p><p className="font-semibold">{metric(daily.session_range_pct_of_open?.median, "%")}</p></div>
              <div className="rounded-lg border p-3"><p className="text-xs text-muted-foreground">Median intraday full-session range</p><p className="font-semibold">{metric(intraday.full_session_range_pct_of_open?.median, "%")}</p></div>
            </div>
            <p className="text-xs text-muted-foreground">
              Method: {report?.method_version || "—"} · cutoff {report?.as_of || "—"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base flex items-center gap-2"><CheckCircle2 className="h-4 w-4" /> Evidence readiness</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            <Readiness label="Daily descriptive coverage" ready={readiness.daily_descriptive_ready} />
            <Readiness label="Intraday descriptive coverage" ready={readiness.intraday_descriptive_ready} />
            <Readiness label="Walk-forward intraday candidate coverage" ready={readiness.walk_forward_intraday_candidate_ready} />
            <p className="text-[11px] text-muted-foreground">{readiness.note || "Coverage gates indicate sample availability only."}</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader><CardTitle className="text-base flex items-center gap-2"><BarChart3 className="h-4 w-4" /> Replay / Focus Lab</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-muted-foreground">Replay outcomes</span><strong>{metric(focus?.replay_plan_outcomes)}</strong></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Ambiguous outcomes</span><strong>{metric(focus?.ambiguous_replay_outcomes)}</strong></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Level reliability runs</span><strong>{metric(focus?.level_reliability_runs)}</strong></div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base flex items-center gap-2"><FlaskConical className="h-4 w-4" /> Prospective evidence</CardTitle></CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{observations.length}</p>
            <p className="text-xs text-muted-foreground mt-1">Stored future-only GAP-001 observations after the frozen hypothesis date.</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base flex items-center gap-2"><FlaskConical className="h-4 w-4" /> Challenger system</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            {scalarChallengerStats.length === 0 ? (
              <p className="text-xs text-muted-foreground">No challenger summary available yet.</p>
            ) : scalarChallengerStats.slice(0, 6).map(([key, value]) => (
              <div key={key} className="flex justify-between gap-3">
                <span className="text-muted-foreground">{key.replaceAll("_", " ")}</span>
                <strong>{String(value)}</strong>
              </div>
            ))}
            <p className="text-[11px] text-muted-foreground">Human approval is required before any soft parameter can be promoted.</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base">Actual BSE trade evidence</CardTitle></CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-4 text-sm">
            {Object.entries(actual || {}).filter(([, value]) => typeof value === "number").map(([key, value]) => (
              <div key={key}><span className="text-muted-foreground">{key.replaceAll("_", " ")}: </span><strong>{String(value)}</strong></div>
            ))}
            {!actual && <span className="text-muted-foreground">No actual-trade statistics available yet.</span>}
          </div>
        </CardContent>
      </Card>

      <div className="rounded-lg border bg-muted/20 p-4 text-xs text-muted-foreground">
        <p className="font-medium text-foreground">Research contract</p>
        <p className="mt-1">
          Strategy edge claimed: {String(doctrine?.strategy_edge_claimed ?? false)} · Win rate claimed: {String(doctrine?.win_rate_claimed ?? false)} · Hidden chain-of-thought persisted: {String(doctrine?.hidden_chain_of_thought_persisted ?? false)}.
        </p>
      </div>
    </div>
  );
}
