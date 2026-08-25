"use client";

import { useEffect, useMemo, useState } from "react";
import { createActualTrade } from "@/lib/api";
import type { TradeBrainAdvisory } from "@/lib/types";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Building2, Loader2, Link2, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

const BSE_TICKER = "BSE";
const BSE_EXCHANGE = "NSE" as const;

function istNowInput(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date());
  const pick = (type: string) => parts.find((p) => p.type === type)?.value || "00";
  return `${pick("year")}-${pick("month")}-${pick("day")}T${pick("hour")}:${pick("minute")}`;
}

function toIstIso(value: string): string | undefined {
  if (!value) return undefined;
  return `${value}:00+05:30`;
}

function candidateNumber(advisory: TradeBrainAdvisory | null | undefined, key: "entry" | "stop_loss" | "take_profit"): number | undefined {
  const geometryValue = advisory?.trade_geometry?.[key];
  if (typeof geometryValue === "number" && Number.isFinite(geometryValue) && geometryValue > 0) return geometryValue;
  const candidate = advisory?.ai_candidate || {};
  const raw = candidate[key];
  return typeof raw === "number" && Number.isFinite(raw) && raw > 0 ? raw : undefined;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  advisoryTaskId?: string;
  ticker?: string;
  exchange?: "NSE" | "BSE";
  researchLabel?: string;
  advisory?: TradeBrainAdvisory | null;
}

export function ActualTradeDialog({
  open,
  onClose,
  onSaved,
  advisoryTaskId,
  researchLabel,
  advisory,
}: Props) {
  const inferredDirection = researchLabel === "SHORT_CANDIDATE" ? "SHORT" : "LONG";
  const inferredMode = advisory?.trade_geometry?.mode === "SWING" || advisory?.ai_candidate?.mode === "SWING"
    ? "SWING"
    : "INTRADAY";
  const suggestedEntry = useMemo(() => candidateNumber(advisory, "entry"), [advisory]);
  const suggestedStop = useMemo(() => candidateNumber(advisory, "stop_loss"), [advisory]);
  const suggestedTarget = useMemo(() => candidateNumber(advisory, "take_profit"), [advisory]);

  const [mode, setMode] = useState<"INTRADAY" | "SWING">(inferredMode);
  const [direction, setDirection] = useState<"LONG" | "SHORT">(inferredDirection);
  const [quantity, setQuantity] = useState("");
  const [entryPrice, setEntryPrice] = useState(suggestedEntry ? String(suggestedEntry) : "");
  const [entryTime, setEntryTime] = useState(istNowInput());
  const [stopLoss, setStopLoss] = useState(suggestedStop ? String(suggestedStop) : "");
  const [takeProfit, setTakeProfit] = useState(suggestedTarget ? String(suggestedTarget) : "");
  const [brokerRef, setBrokerRef] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setMode(inferredMode);
    setDirection(inferredMode === "SWING" ? "LONG" : inferredDirection);
    setEntryPrice(suggestedEntry ? String(suggestedEntry) : "");
    setStopLoss(suggestedStop ? String(suggestedStop) : "");
    setTakeProfit(suggestedTarget ? String(suggestedTarget) : "");
    setEntryTime(istNowInput());
  }, [open, inferredMode, inferredDirection, suggestedEntry, suggestedStop, suggestedTarget]);

  const save = async () => {
    const qty = Number(quantity);
    const entry = Number(entryPrice);
    if (!Number.isInteger(qty) || qty <= 0) return toast.error("Enter a valid quantity");
    if (!Number.isFinite(entry) || entry <= 0) return toast.error("Enter a valid entry price");
    if (mode === "SWING" && direction === "SHORT") return toast.error("SWING is LONG-only in Trade Brain");

    setSaving(true);
    try {
      const trade: any = await createActualTrade({
        ticker: BSE_TICKER,
        exchange: BSE_EXCHANGE,
        mode,
        direction,
        quantity: qty,
        entry_price: entry,
        entry_timestamp: toIstIso(entryTime),
        advisory_task_id: advisoryTaskId || undefined,
        stop_loss: stopLoss ? Number(stopLoss) : undefined,
        take_profit: takeProfit ? Number(takeProfit) : undefined,
        broker_order_ref: brokerRef || undefined,
        notes: notes || undefined,
      });
      toast.success("BSE Ltd actual trade recorded as OPEN");
      if (trade.advisory_alignment === "DIRECTION_MISMATCH") {
        toast.warning("Actual direction differs from the linked advisory; mismatch was preserved.");
      }
      onSaved();
      onClose();
      setQuantity("");
      setBrokerRef("");
      setNotes("");
    } catch (e: any) {
      toast.error(e.message || "Failed to record actual BSE trade");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>I Took This BSE Trade</DialogTitle>
          <p className="text-xs text-muted-foreground">
            Records what you actually did at your broker. This screen never places or modifies a broker order.
          </p>
        </DialogHeader>

        <div className="flex items-center gap-3 rounded-lg border bg-muted/20 p-3">
          <Building2 className="h-5 w-5 text-green-600" />
          <div className="flex-1">
            <p className="text-sm font-semibold">BSE Ltd · NSE:BSE</p>
            <p className="text-[11px] text-muted-foreground">ISIN INE118H01025 · fixed Trade Brain instrument</p>
          </div>
          <Badge variant="outline">NSE</Badge>
        </div>

        {advisoryTaskId && (
          <div className="flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50/40 p-3 text-xs">
            <Link2 className="h-4 w-4 text-blue-600 mt-0.5" />
            <div>
              <div className="font-medium">Linked to advisory {advisoryTaskId}</div>
              <div className="text-muted-foreground">The exact advisory snapshot is frozen into the actual-trade record.</div>
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium mb-1 block">Mode</label>
            <select
              className="h-10 w-full rounded-md border bg-background px-3 text-sm"
              value={mode}
              onChange={(e) => {
                const next = e.target.value as "INTRADAY" | "SWING";
                setMode(next);
                if (next === "SWING") setDirection("LONG");
              }}
            >
              <option value="INTRADAY">INTRADAY</option>
              <option value="SWING">SWING</option>
            </select>
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">Direction</label>
            <select className="h-10 w-full rounded-md border bg-background px-3 text-sm" value={direction} onChange={(e) => setDirection(e.target.value as "LONG" | "SHORT")}>
              <option value="LONG">LONG</option>
              {mode === "INTRADAY" && <option value="SHORT">SHORT</option>}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">Quantity</label>
            <Input type="number" min="1" step="1" value={quantity} onChange={(e) => setQuantity(e.target.value)} placeholder="e.g. 200" />
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">Actual Entry Price (₹)</label>
            <Input type="number" min="0" step="0.01" value={entryPrice} onChange={(e) => setEntryPrice(e.target.value)} placeholder="Actual broker fill" />
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">Actual Entry Time (IST)</label>
            <Input type="datetime-local" value={entryTime} onChange={(e) => setEntryTime(e.target.value)} />
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">Broker Order / Trade Ref (optional)</label>
            <Input value={brokerRef} onChange={(e) => setBrokerRef(e.target.value)} placeholder="For later reconciliation" />
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">Stop Loss (optional)</label>
            <Input type="number" step="0.01" value={stopLoss} onChange={(e) => setStopLoss(e.target.value)} />
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">Primary Target (optional)</label>
            <Input type="number" step="0.01" value={takeProfit} onChange={(e) => setTakeProfit(e.target.value)} />
          </div>
        </div>

        <div>
          <label className="text-xs font-medium mb-1 block">Notes (optional)</label>
          <textarea className="min-h-20 w-full rounded-md border bg-background p-3 text-sm" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Why you took it, execution notes, etc." />
        </div>

        <div className="rounded-lg border bg-muted/30 p-3 flex gap-2 text-xs text-muted-foreground">
          <ShieldCheck className="h-4 w-4 flex-shrink-0" />
          <span>Actual BSE trades are stored separately from paper/replay outcomes. Estimated charges can later be replaced with broker-statement charges for a closed slice.</span>
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button onClick={save} disabled={saving}>
            {saving && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
            Record OPEN BSE Trade
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
