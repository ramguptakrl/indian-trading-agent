"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { getActualTradeStats, getQuote, listActualTrades, markActualTrade } from "@/lib/api";
import { getPositionGuardian } from "@/lib/guardian";
import type { ActualTrade, ActualTradeMark } from "@/lib/types";
import { ActualTradeDialog } from "@/components/trades/ActualTradeDialog";
import { CloseActualTradeDialog } from "@/components/trades/CloseActualTradeDialog";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { RefreshCw, Plus, Link2, AlertTriangle, LockKeyhole, ShieldCheck } from "lucide-react";

const money = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value)
    ? "-"
    : `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const pnlClass = (value: number | null | undefined) =>
  value == null ? "" : value >= 0 ? "text-green-600" : "text-red-600";
const isBseTrade = (trade: ActualTrade) =>
  String(trade.ticker || "").toUpperCase().startsWith("BSE") && trade.exchange === "NSE";

function istDateParts(value: Date): [number, number, number] {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(value);
  const n = (type: string) => Number(parts.find((p) => p.type === type)?.value || "0");
  return [n("year"), n("month"), n("day")];
}

function elapsedIstCalendarDays(entryIso: string): number {
  const [ey, em, ed] = istDateParts(new Date(entryIso));
  const [ny, nm, nd] = istDateParts(new Date());
  return Math.max(0, Math.floor((Date.UTC(ny, nm - 1, nd) - Date.UTC(ey, em - 1, ed)) / 86400000));
}

function guardianTone(priority: string | undefined) {
  const value = String(priority || "").toUpperCase();
  if (value === "CRITICAL") return "text-red-700";
  if (value === "HIGH") return "text-amber-700";
  return "text-green-700";
}

export default function ActualTradesPage() {
  const [trades, setTrades] = useState<ActualTrade[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [marks, setMarks] = useState<Record<string, ActualTradeMark>>({});
  const [guardian, setGuardian] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [openDialog, setOpenDialog] = useState(false);
  const [closing, setClosing] = useState<ActualTrade | null>(null);

  const refreshMarks = useCallback(async (currentTrades?: ActualTrade[]) => {
    const sourceTrades = currentTrades || trades;
    const openTrades = sourceTrades.filter((t) => t.status !== "CLOSED" && t.open_quantity > 0);
    const updates = await Promise.all(
      openTrades.map(async (trade) => {
        try {
          const quote: any = await getQuote("BSE");
          const price = Number(quote.price ?? quote.last_price ?? quote.ltp);
          if (!Number.isFinite(price) || price <= 0) return null;
          const source = String(
            quote.price_source || quote.source || quote.source_key || quote.transport || "CURRENT_BSE_QUOTE"
          );
          const mtfDays = trade.mode === "SWING" ? elapsedIstCalendarDays(trade.entry_timestamp) : undefined;
          const mark: any = await markActualTrade(trade.trade_id, price, source, mtfDays);
          return [trade.trade_id, mark] as const;
        } catch {
          return null;
        }
      })
    );
    const next: Record<string, ActualTradeMark> = {};
    for (const item of updates) if (item) next[item[0]] = item[1];
    setMarks(next);
  }, [trades]);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const [tradeResp, statsResp] = await Promise.all([listActualTrades(), getActualTradeStats()]);
      const nextTrades = ((tradeResp as any).trades || []).filter(isBseTrade);
      setTrades(nextTrades);
      setStats(statsResp);
      await refreshMarks(nextTrades);
      try {
        setGuardian(await getPositionGuardian());
      } catch (error) {
        setGuardian({ status: "GUARDIAN_UNAVAILABLE", reason: error instanceof Error ? error.message : "Guardian unavailable" });
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [refreshMarks]);

  useEffect(() => {
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const id = window.setInterval(async () => {
      await refreshMarks();
      try {
        setGuardian(await getPositionGuardian());
      } catch {
        // Keep the last known guardian snapshot instead of replacing it with invented state.
      }
    }, 30000);
    return () => window.clearInterval(id);
  }, [refreshMarks]);

  const openTrades = useMemo(() => trades.filter((t) => t.status !== "CLOSED"), [trades]);
  const closedTrades = useMemo(() => trades.filter((t) => t.status === "CLOSED"), [trades]);
  const guardianByTrade = useMemo(() => {
    const entries = (guardian?.positions || []).map((item: any) => [String(item?.trade?.trade_id || ""), item]);
    return Object.fromEntries(entries.filter(([key]: [string, any]) => key));
  }, [guardian]);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold">Actual BSE Trades</h1>
            <Badge variant="outline">NSE:BSE</Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            BSE Ltd trades you actually took at your broker after an advisory. INTRADAY is same-session; SWING is Zerodha MTF-funded. Manual tracking only.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={load} disabled={refreshing}>
            <RefreshCw className={`h-4 w-4 mr-2 ${refreshing ? "animate-spin" : ""}`} /> Refresh
          </Button>
          <Button onClick={() => setOpenDialog(true)}>
            <Plus className="h-4 w-4 mr-2" /> Log BSE Trade
          </Button>
        </div>
      </div>

      <div className="rounded-lg border border-amber-200 bg-amber-50/40 p-3 text-xs flex items-start gap-2">
        <LockKeyhole className="h-4 w-4 mt-0.5 text-amber-700" />
        <div><span className="font-medium">Execution boundary:</span> OPEN/CLOSE here only updates this BSE journal. You execute the real trade yourself at the broker.</div>
      </div>

      <div className="rounded-lg border p-4 text-sm flex items-start gap-3">
        <ShieldCheck className="h-5 w-5 mt-0.5" />
        <div className="space-y-1">
          <div className="font-semibold">Position Guardian</div>
          <div>
            Status: <span className="font-medium">{guardian?.status || "LOADING"}</span>
            {guardian?.current_price != null ? ` · accepted BSE price ${money(Number(guardian.current_price))}` : ""}
          </div>
          <div className="text-xs text-muted-foreground">
            Event/news risk: {guardian?.event_risk || guardian?.guardian_context?.event_risk || "UNKNOWN"}
            {` · BSE correction: ${guardian?.correction_state || guardian?.guardian_context?.correction_state || "UNKNOWN"}`}
            {` · Broader market: ${guardian?.guardian_context?.broader_market_correction_state || "UNKNOWN"}`}
          </div>
          {guardian?.reason && <div className="text-xs text-amber-700">{guardian.reason}</div>}
          <div className="text-[11px] text-muted-foreground">Read-only risk review. Guardian cannot place, modify or cancel broker orders.</div>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4">
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Open / Partial</p><p className="text-2xl font-bold">{(stats?.open || 0) + (stats?.partially_closed || 0)}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Closed</p><p className="text-2xl font-bold">{stats?.closed || 0}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Realized Net P&L</p><p className={`text-2xl font-bold ${pnlClass(stats?.realized_net_pnl)}`}>{money(stats?.realized_net_pnl || 0)}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">MTF SWING Logged</p><p className="text-2xl font-bold">{stats?.swing_mtf || 0}</p></CardContent></Card>
      </div>

      <div>
        <h2 className="font-semibold mb-2">Open BSE Positions ({openTrades.length})</h2>
        <Card><CardContent className="p-0"><Table>
          <TableHeader><TableRow>
            <TableHead>Instrument</TableHead><TableHead>Mode</TableHead><TableHead>Direction</TableHead><TableHead>Qty</TableHead>
            <TableHead className="text-right">Entry</TableHead><TableHead className="text-right">Current</TableHead><TableHead className="text-right">Est. Open Net</TableHead>
            <TableHead className="text-right">Realized Net</TableHead><TableHead>Plan</TableHead><TableHead>Guardian</TableHead><TableHead>Source</TableHead><TableHead></TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {loading ? (
              <TableRow><TableCell colSpan={12} className="text-center py-8 text-muted-foreground">Loading...</TableCell></TableRow>
            ) : openTrades.length === 0 ? (
              <TableRow><TableCell colSpan={12} className="text-center py-8 text-muted-foreground">No actual BSE open trades.</TableCell></TableRow>
            ) : openTrades.map((trade) => {
              const mark = marks[trade.trade_id];
              const guarded = guardianByTrade[trade.trade_id] as any;
              const risk = guarded?.risk;
              return (
                <TableRow key={trade.trade_id}>
                  <TableCell className="font-semibold">BSE Ltd<div className="text-[10px] text-muted-foreground">NSE:BSE</div></TableCell>
                  <TableCell>
                    <Badge variant="outline">{trade.mode}{trade.mode === "SWING" ? " · MTF" : ""}</Badge>
                    {trade.mode === "SWING" && <div className="text-[10px] text-muted-foreground mt-1">Funded {money(trade.funded_amount)}{mark?.mtf_interest_days != null ? ` · est ${mark.mtf_interest_days}d` : ""}</div>}
                  </TableCell>
                  <TableCell className={trade.direction === "LONG" ? "text-green-600" : "text-red-600"}>{trade.direction}</TableCell>
                  <TableCell>{trade.open_quantity}/{trade.original_quantity}</TableCell>
                  <TableCell className="text-right">{money(trade.avg_entry_price)}</TableCell>
                  <TableCell className="text-right">{mark ? money(mark.current_price) : "-"}</TableCell>
                  <TableCell className={`text-right font-medium ${pnlClass(mark?.estimated_open_net_pnl_if_closed_now)}`}>{mark ? money(mark.estimated_open_net_pnl_if_closed_now) : "-"}</TableCell>
                  <TableCell className={`text-right ${pnlClass(trade.realized_net_pnl)}`}>{money(trade.realized_net_pnl)}</TableCell>
                  <TableCell className="text-xs"><div>SL: {trade.stop_loss ? money(trade.stop_loss) : "-"}</div><div>Primary TP: {trade.take_profit ? money(trade.take_profit) : "-"}</div></TableCell>
                  <TableCell className="text-xs max-w-48">
                    {risk ? <div className={guardianTone(risk.priority)}><div className="font-semibold">{risk.state}</div><div className="mt-1 text-[10px] leading-snug">{risk.reason}</div></div> : <span className="text-muted-foreground">Awaiting audited Guardian context</span>}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground max-w-28 truncate" title={mark?.source}>{mark?.source || "No current mark"}</TableCell>
                  <TableCell><Button size="sm" onClick={() => setClosing(trade)}>Close</Button></TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table></CardContent></Card>
      </div>

      <div>
        <h2 className="font-semibold mb-2">Closed Actual BSE Trades ({closedTrades.length})</h2>
        <Card><CardContent className="p-0"><Table>
          <TableHeader><TableRow><TableHead>Instrument</TableHead><TableHead>Mode / Direction</TableHead><TableHead>Entry</TableHead><TableHead>Qty</TableHead><TableHead className="text-right">Gross P&L</TableHead><TableHead className="text-right">Charges Used</TableHead><TableHead className="text-right">Net P&L</TableHead><TableHead>Advisory</TableHead><TableHead>Integrity</TableHead></TableRow></TableHeader>
          <TableBody>
            {closedTrades.length === 0 ? (
              <TableRow><TableCell colSpan={9} className="text-center py-8 text-muted-foreground">No closed actual BSE trades yet.</TableCell></TableRow>
            ) : closedTrades.map((trade) => (
              <TableRow key={trade.trade_id}>
                <TableCell className="font-semibold">BSE Ltd<div className="text-[10px] text-muted-foreground">{new Date(trade.entry_timestamp).toLocaleString()}</div></TableCell>
                <TableCell><div>{trade.mode}{trade.mode === "SWING" ? " · MTF" : ""}</div><div className="text-xs text-muted-foreground">{trade.direction}</div></TableCell>
                <TableCell>{money(trade.avg_entry_price)}</TableCell><TableCell>{trade.original_quantity}</TableCell>
                <TableCell className={`text-right ${pnlClass(trade.realized_gross_pnl)}`}>{money(trade.realized_gross_pnl)}</TableCell>
                <TableCell className="text-right">{money(trade.estimated_or_actual_charges)}</TableCell>
                <TableCell className={`text-right font-semibold ${pnlClass(trade.realized_net_pnl)}`}>{money(trade.realized_net_pnl)}</TableCell>
                <TableCell>{trade.advisory_task_id ? <Link className="text-primary text-xs hover:underline inline-flex items-center gap-1" href={`/analysis/${trade.advisory_task_id}`}><Link2 className="h-3 w-3" /> View advisory</Link> : <span className="text-xs text-muted-foreground">Manual</span>}</TableCell>
                <TableCell>{trade.entry_policy_violation || trade.mtf_metadata_status === "LEGACY_MTF_METADATA_MISSING" ? <span className="text-xs text-amber-700 inline-flex gap-1"><AlertTriangle className="h-3 w-3" /> Review integrity</span> : <span className="text-xs text-green-700">Recorded cleanly</span>}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table></CardContent></Card>
      </div>

      <ActualTradeDialog open={openDialog} onClose={() => setOpenDialog(false)} onSaved={load} />
      <CloseActualTradeDialog open={!!closing} trade={closing} onClose={() => setClosing(null)} onSaved={load} />
    </div>
  );
}
