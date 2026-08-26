"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getAnalysisHistory } from "@/lib/api";
import type { AnalysisHistoryItem } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { DollarSign, Clock, CheckCircle2 } from "lucide-react";
import { PnLDialog } from "@/components/history/PnLDialog";

const signalColors: Record<string, string> = {
  LONG_CANDIDATE: "bg-green-500/20 text-green-700",
  SHORT_CANDIDATE: "bg-red-500/20 text-red-700",
  EXIT_CANDIDATE: "bg-amber-500/20 text-amber-700",
  WAIT: "bg-yellow-500/20 text-yellow-700",
  NO_TRADE: "bg-slate-500/15 text-slate-700",
};

const pnlStatusColors: Record<string, string> = {
  win: "bg-green-500/20 text-green-700",
  loss: "bg-red-500/20 text-red-700",
  breakeven: "bg-yellow-500/20 text-yellow-700",
  open: "bg-blue-500/20 text-blue-700",
  pending: "bg-muted text-muted-foreground",
};

const labelText = (value: string) => value.replaceAll("_", " ");
const isBseAnalysis = (item: AnalysisHistoryItem) => String(item.ticker || "").toUpperCase().startsWith("BSE");

function horizonLabel(item: any) {
  const explicit = String(item.requested_trade_mode || "").toUpperCase();
  if (explicit === "SWING") return "SWING · MTF";
  if (explicit === "INTRADAY") return "INTRADAY";
  const task = String(item.task_id || "");
  if (task.startsWith("sw-")) return "SWING · MTF";
  if (task.startsWith("id-")) return "INTRADAY";
  return "LEGACY";
}

export default function HistoryPage() {
  const [analyses, setAnalyses] = useState<AnalysisHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialog, setDialog] = useState<{ taskId: string; signal: string } | null>(null);

  const load = () => {
    setLoading(true);
    getAnalysisHistory(200)
      .then((history: any) => setAnalyses((Array.isArray(history) ? history : []).filter(isBseAnalysis)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const closed = analyses.filter((a) => ["win", "loss", "breakeven"].includes(a.pnl_status || ""));
  const open = analyses.filter((a) => a.pnl_status === "open");
  const untracked = analyses.filter((a) => !a.pnl_status || a.pnl_status === "pending");
  const wins = closed.filter((a) => a.pnl_status === "win").length;
  const losses = closed.filter((a) => a.pnl_status === "loss").length;
  const totalPnlPct = closed.reduce((sum, a) => sum + (a.pnl_pct || 0), 0);
  const winRate = closed.length ? Math.round((wins / closed.length) * 100) : 0;

  return (
    <div className="p-6 space-y-5">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-bold">BSE Analysis Outcomes</h1>
          <Badge variant="outline">NSE:BSE</Badge>
        </div>
        <p className="text-sm text-muted-foreground mt-1">
          Research history only. INTRADAY and SWING · MTF are shown separately; real fills belong in Actual Trades.
        </p>
      </div>

      {closed.length > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Card><CardContent className="p-3 text-center"><p className="text-[11px] text-muted-foreground">Observed Win Rate</p><p className="text-lg font-bold">{winRate}%</p><p className="text-[10px] text-muted-foreground">{wins}W / {losses}L</p></CardContent></Card>
          <Card><CardContent className="p-3 text-center"><p className="text-[11px] text-muted-foreground">Avg Observed Return</p><p className={`text-lg font-bold ${totalPnlPct / closed.length >= 0 ? "text-green-600" : "text-red-600"}`}>{(totalPnlPct / closed.length).toFixed(2)}%</p></CardContent></Card>
          <Card><CardContent className="p-3 text-center"><p className="text-[11px] text-muted-foreground">Sum Observed %</p><p className={`text-lg font-bold ${totalPnlPct >= 0 ? "text-green-600" : "text-red-600"}`}>{totalPnlPct >= 0 ? "+" : ""}{totalPnlPct.toFixed(2)}%</p></CardContent></Card>
          <Card><CardContent className="p-3 text-center"><p className="text-[11px] text-muted-foreground">Closed Outcomes</p><p className="text-lg font-bold">{closed.length}</p><p className="text-[10px] text-muted-foreground">{open.length} open</p></CardContent></Card>
        </div>
      )}

      <Tabs defaultValue="all">
        <TabsList>
          <TabsTrigger value="all">All ({analyses.length})</TabsTrigger>
          <TabsTrigger value="open"><Clock className="h-3 w-3 mr-1" /> Open ({open.length})</TabsTrigger>
          <TabsTrigger value="closed"><CheckCircle2 className="h-3 w-3 mr-1" /> Closed ({closed.length})</TabsTrigger>
          <TabsTrigger value="untracked">Untracked ({untracked.length})</TabsTrigger>
        </TabsList>

        {[
          { key: "all", data: analyses, empty: "No BSE analyses yet." },
          { key: "open", data: open, empty: "No open observed BSE outcomes." },
          { key: "closed", data: closed, empty: "No closed observed BSE outcomes yet." },
          { key: "untracked", data: untracked, empty: "All BSE analyses have an observed outcome status." },
        ].map((tab) => (
          <TabsContent key={tab.key} value={tab.key}>
            <Card>
              <CardContent className="p-0">
                <Table>
                  <TableHeader><TableRow>
                    <TableHead>India Date</TableHead>
                    <TableHead>Horizon</TableHead>
                    <TableHead>Verdict</TableHead>
                    <TableHead className="text-right">Entry</TableHead>
                    <TableHead className="text-right">Exit</TableHead>
                    <TableHead className="text-right">P&L</TableHead>
                    <TableHead>Outcome</TableHead>
                    <TableHead></TableHead>
                  </TableRow></TableHeader>
                  <TableBody>
                    {loading ? (
                      <TableRow><TableCell colSpan={8} className="text-center py-8 text-muted-foreground">Loading...</TableCell></TableRow>
                    ) : tab.data.length === 0 ? (
                      <TableRow><TableCell colSpan={8} className="text-center py-8 text-muted-foreground">
                        {tab.empty} {tab.key === "all" && <Link href="/analysis" className="text-primary hover:underline">Analyze BSE</Link>}
                      </TableCell></TableRow>
                    ) : tab.data.map((a: any) => (
                      <TableRow key={a.task_id}>
                        <TableCell className="text-sm font-medium">{a.trade_date}</TableCell>
                        <TableCell><Badge variant="outline">{horizonLabel(a)}</Badge></TableCell>
                        <TableCell><Badge variant="outline" className={signalColors[a.signal] || "bg-slate-500/10 text-slate-700"}>{labelText(a.signal)}</Badge></TableCell>
                        <TableCell className="text-right text-sm">{a.entry_price ? `₹${a.entry_price}` : "-"}</TableCell>
                        <TableCell className="text-right text-sm">{a.exit_price ? `₹${a.exit_price}` : "-"}</TableCell>
                        <TableCell className={`text-right text-sm ${(a.pnl_pct || 0) >= 0 ? "text-green-600" : "text-red-600"}`}>{a.pnl_pct != null ? `${a.pnl_pct >= 0 ? "+" : ""}${a.pnl_pct}%` : "-"}</TableCell>
                        <TableCell>{a.pnl_status ? <Badge variant="outline" className={pnlStatusColors[a.pnl_status] || ""}>{a.pnl_status}</Badge> : <span className="text-xs text-muted-foreground">-</span>}</TableCell>
                        <TableCell><div className="flex items-center justify-end gap-2">
                          <Link href={`/analysis/${a.task_id}`} className="text-xs text-primary hover:underline">View</Link>
                          <Button size="sm" variant="ghost" className="h-6 px-2 text-xs" onClick={() => setDialog({ taskId: a.task_id, signal: a.signal })}>
                            <DollarSign className="h-3 w-3 mr-1" /> {a.pnl_status === "open" ? "Close" : "Log"}
                          </Button>
                        </div></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </TabsContent>
        ))}
      </Tabs>

      {dialog && (
        <PnLDialog
          open={!!dialog}
          onClose={() => setDialog(null)}
          taskId={dialog.taskId}
          ticker="BSE"
          signal={dialog.signal}
          onSaved={load}
        />
      )}
    </div>
  );
}
