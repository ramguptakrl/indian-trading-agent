"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { getActualTradeStats, getQuote, listActualTrades, markActualTrade } from "@/lib/api";
import type { ActualTrade, ActualTradeMark } from "@/lib/types";
import { ActualTradeDialog } from "@/components/trades/ActualTradeDialog";
import { CloseActualTradeDialog } from "@/components/trades/CloseActualTradeDialog";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { RefreshCw, Plus, Link2, AlertTriangle, LockKeyhole } from "lucide-react";

const money = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value) ? "-" : `Rs.${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

const pnlClass = (value: number | null | undefined) =>
  value == null ? "" : value >= 0 ? "text-green-600" : "text-red-600";

export default function ActualTradesPage() {
  const [trades, setTrades] = useState<ActualTrade[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [marks, setMarks] = useState<Record<string, ActualTradeMark>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [openDialog, setOpenDialog] = useState(false);
  const [closing, setClosing] = useState<ActualTrade | null>(null);

  const loadBase = useCallback(async () => {
    const [tradeResp, statsResp]: any[] = await Promise.all([listActualTrades(), getActualTradeStats()]);
    setTrades(tradeResp.trades || []);
    setStats(statsResp);
  }, []);

  const refreshMarks = useCallback(async (currentTrades?: ActualTrade[]) => {
    const sourceTrades = currentTrades || trades;
    const openTrades = sourceTrades.filter((t) => t.status !== "CLOSED" && t.open_quantity > 0);
    const updates = await Promise.all(
      openTrades.map(async (trade) => {
        try {
          const quote: any = await getQuote(trade.ticker);
          const price = Number(quote.price ?? quote.last_price ?? quote.ltp);
          if (!Number.isFinite(price) || price <= 0) return null;
          const source = String(quote.source || quote.source_key || quote.transport || "CURRENT_QUOTE");
          const mark: any = await markActualTrade(trade.trade_id, price, source);
          return [trade.trade_id, mark] as const;
        } catch {
          return null;
        }
      }),
    );
    const next: Record<string, ActualTradeMark> = {};
    for (const item of updates) if (item) next[item[0]] = item[1];
    setMarks(next);
  }, [trades]);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const tradeResp: any = await listActualTrades();
      const nextTrades = tradeResp.trades || [];
      const statsResp: any = await getActualTradeStats();
      setTrades(nextTrades);
      setStats(statsResp);
      await refreshMarks(nextTrades);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [refreshMarks]);

  useEffect(() => {
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const id = window.setInterval(() => refreshMarks(), 30000);
    return () => window.clearInterval(id);
  }, [refreshMarks]);

  const openTrades = useMemo(() => trades.filter((t) => t.status !== "CLOSED"), [trades]);
  const closedTrades = useMemo(() => trades.filter((t) => t.status === "CLOSED"), [trades]);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Actual Trades</h1>
          <p className="text-sm text-muted-foreground">
            Trades you actually took at your broker after an advisory. Manual tracking only; Trade Brain cannot place or close broker orders.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={load} disabled={refreshing}>
            <RefreshCw className={`h-4 w-4 mr-2 ${refreshing ? "animate-spin" : ""}`} /> Refresh
          </Button>
          <Button onClick={() => setOpenDialog(true)}>
            <Plus className="h-4 w-4 mr-2" /> Log Manual Trade
          </Button>
        </div>
      </div>

      <div className="rounded-lg border border-amber-200 bg-amber-50/40 p-3 text-xs flex items-start gap-2">
        <LockKeyhole className="h-4 w-4 mt-0.5 text-amber-700" />
        <div>
          <span className="font-medium">Execution boundary:</span> clicking OPEN/CLOSE here only updates this journal. You must execute the real trade yourself in Zerodha or another broker.
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4">
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Open / Partial</p><p className="text-2xl font-bold">{(stats?.open || 0) + (stats?.partially_closed || 0)}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Closed</p><p className="text-2xl font-bold">{stats?.closed || 0}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Realized Net P&L</p><p className={`text-2xl font-bold ${pnlClass(stats?.realized_net_pnl)}`}>{money(stats?.realized_net_pnl || 0)}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Linked to Advisory</p><p className="text-2xl font-bold">{stats?.linked_to_advisory || 0}</p></CardContent></Card>
      </div>

      <div>
        <h2 className="font-semibold mb-2">Open Positions ({openTrades.length})</h2>
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader><TableRow>
                <TableHead>Ticker</TableHead><TableHead>Mode</TableHead><TableHead>Direction</TableHead><TableHead>Qty</TableHead>
                <TableHead className="text-right">Entry</TableHead><TableHead className="text-right">Current</TableHead>
                <TableHead className="text-right">Est. Open Net</TableHead><TableHead className="text-right">Realized Net</TableHead>
                <TableHead>Plan</TableHead><TableHead>Source</TableHead><TableHead></TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {loading ? <TableRow><TableCell colSpan={11} className="text-center py-8 text-muted-foreground">Loading...</TableCell></TableRow> : openTrades.length === 0 ? (
                  <TableRow><TableCell colSpan={11} className="text-center py-8 text-muted-foreground">No actual open trades. From an advisory, use “I TOOK THIS TRADE”, or log one manually here.</TableCell></TableRow>
                ) : openTrades.map((trade) => {
                  const mark = marks[trade.trade_id];
                  return <TableRow key={trade.trade_id}>
                    <TableCell className="font-semibold">{trade.ticker}<div className="text-[10px] text-muted-foreground">{trade.exchange}</div></TableCell>
                    <TableCell><Badge variant="outline">{trade.mode}</Badge></TableCell>
                    <TableCell className={trade.direction === "LONG" ? "text-green-600" : "text-red-600"}>{trade.direction}</TableCell>
                    <TableCell>{trade.open_quantity}/{trade.original_quantity}</TableCell>
                    <TableCell className="text-right">{money(trade.avg_entry_price)}</TableCell>
                    <TableCell className="text-right">{mark ? money(mark.current_price) : "-"}</TableCell>
                    <TableCell className={`text-right font-medium ${pnlClass(mark?.estimated_open_net_pnl_if_closed_now)}`}>{mark ? money(mark.estimated_open_net_pnl_if_closed_now) : "-"}</TableCell>
                    <TableCell className={`text-right ${pnlClass(trade.realized_net_pnl)}`}>{money(trade.realized_net_pnl)}</TableCell>
                    <TableCell className="text-xs">
                      <div>SL: {trade.stop_loss ? money(trade.stop_loss) : "-"}</div><div>TP: {trade.take_profit ? money(trade.take_profit) : "-"}</div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground max-w-28 truncate" title={mark?.source}>{mark?.source || "No current mark"}</TableCell>
                    <TableCell><Button size="sm" onClick={() => setClosing(trade)}>Close</Button></TableCell>
                  </TableRow>;
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <div>
        <h2 className="font-semibold mb-2">Closed Actual Trades ({closedTrades.length})</h2>
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader><TableRow>
                <TableHead>Ticker</TableHead><TableHead>Mode / Direction</TableHead><TableHead>Entry</TableHead><TableHead>Qty</TableHead>
                <TableHead className="text-right">Gross P&L</TableHead><TableHead className="text-right">Charges Used</TableHead><TableHead className="text-right">Net P&L</TableHead>
                <TableHead>Advisory</TableHead><TableHead>Integrity</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {closedTrades.length === 0 ? <TableRow><TableCell colSpan={9} className="text-center py-8 text-muted-foreground">No closed actual trades yet.</TableCell></TableRow> : closedTrades.map((trade) => (
                  <TableRow key={trade.trade_id}>
                    <TableCell className="font-semibold">{trade.ticker}<div className="text-[10px] text-muted-foreground">{new Date(trade.entry_timestamp).toLocaleString()}</div></TableCell>
                    <TableCell><div>{trade.mode}</div><div className="text-xs text-muted-foreground">{trade.direction}</div></TableCell>
                    <TableCell>{money(trade.avg_entry_price)}</TableCell><TableCell>{trade.original_quantity}</TableCell>
                    <TableCell className={`text-right ${pnlClass(trade.realized_gross_pnl)}`}>{money(trade.realized_gross_pnl)}</TableCell>
                    <TableCell className="text-right">{money(trade.estimated_or_actual_charges)}</TableCell>
                    <TableCell className={`text-right font-semibold ${pnlClass(trade.realized_net_pnl)}`}>{money(trade.realized_net_pnl)}</TableCell>
                    <TableCell>{trade.advisory_task_id ? <Link className="text-primary text-xs hover:underline inline-flex items-center gap-1" href={`/analysis/${trade.advisory_task_id}`}><Link2 className="h-3 w-3" /> View advisory</Link> : <span className="text-xs text-muted-foreground">Manual</span>}</TableCell>
                    <TableCell>{trade.entry_policy_violation ? <span className="text-xs text-amber-700 inline-flex gap-1"><AlertTriangle className="h-3 w-3" /> Review violation</span> : <span className="text-xs text-green-700">Recorded cleanly</span>}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <ActualTradeDialog open={openDialog} onClose={() => setOpenDialog(false)} onSaved={load} />
      <CloseActualTradeDialog open={!!closing} trade={closing} onClose={() => setClosing(null)} onSaved={load} />
    </div>
  );
}
