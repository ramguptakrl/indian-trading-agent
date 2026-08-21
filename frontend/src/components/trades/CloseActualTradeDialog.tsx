"use client";

import { useEffect, useState } from "react";
import { closeActualTrade } from "@/lib/api";
import type { ActualTrade } from "@/lib/types";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

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

interface Props {
  open: boolean;
  trade: ActualTrade | null;
  onClose: () => void;
  onSaved: () => void;
}

export function CloseActualTradeDialog({ open, trade, onClose, onSaved }: Props) {
  const [quantity, setQuantity] = useState("");
  const [exitPrice, setExitPrice] = useState("");
  const [exitTime, setExitTime] = useState(istNowInput());
  const [actualCharges, setActualCharges] = useState("");
  const [brokerRef, setBrokerRef] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || !trade) return;
    setQuantity(String(trade.open_quantity));
    setExitTime(istNowInput());
    setExitPrice("");
    setActualCharges("");
    setBrokerRef("");
    setNotes("");
  }, [open, trade]);

  if (!trade) return null;

  const save = async () => {
    const qty = Number(quantity);
    const price = Number(exitPrice);
    if (!Number.isInteger(qty) || qty <= 0 || qty > trade.open_quantity) {
      toast.error(`Close quantity must be 1-${trade.open_quantity}`);
      return;
    }
    if (!Number.isFinite(price) || price <= 0) {
      toast.error("Enter the actual exit fill price");
      return;
    }
    const charges = actualCharges ? Number(actualCharges) : undefined;
    if (charges !== undefined && (!Number.isFinite(charges) || charges < 0)) {
      toast.error("Actual charges must be zero or positive");
      return;
    }

    setSaving(true);
    try {
      const updated: any = await closeActualTrade(trade.trade_id, {
        quantity: qty,
        exit_price: price,
        exit_timestamp: `${exitTime}:00+05:30`,
        actual_charges_override: charges,
        broker_order_ref: brokerRef || undefined,
        notes: notes || undefined,
      });
      toast.success(
        updated.status === "CLOSED"
          ? `${trade.ticker} actual trade CLOSED`
          : `${qty} shares closed; ${updated.open_quantity} remain open`,
      );
      onSaved();
      onClose();
    } catch (e: any) {
      toast.error(e.message || "Failed to close actual trade");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Close {trade.ticker} Actual Trade</DialogTitle>
          <p className="text-xs text-muted-foreground">
            {trade.mode} {trade.direction} · Entry Rs.{trade.avg_entry_price} · {trade.open_quantity} currently open
          </p>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium mb-1 block">Quantity to Close</label>
              <Input type="number" min="1" max={trade.open_quantity} step="1" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block">Actual Exit Price (Rs.)</label>
              <Input type="number" min="0" step="0.01" value={exitPrice} onChange={(e) => setExitPrice(e.target.value)} autoFocus />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">Actual Exit Time (IST)</label>
            <Input type="datetime-local" value={exitTime} onChange={(e) => setExitTime(e.target.value)} />
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">Actual Charges for This Closed Slice (optional)</label>
            <Input type="number" min="0" step="0.01" value={actualCharges} onChange={(e) => setActualCharges(e.target.value)} placeholder="Leave blank to use resident cost estimate" />
            <p className="mt-1 text-[11px] text-muted-foreground">Use this if you copy the actual broker-statement charge amount. Otherwise the journal keeps an estimate.</p>
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">Broker Exit Ref (optional)</label>
            <Input value={brokerRef} onChange={(e) => setBrokerRef(e.target.value)} />
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">Exit Notes (optional)</label>
            <textarea className="min-h-20 w-full rounded-md border bg-background p-3 text-sm" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose} disabled={saving}>Cancel</Button>
            <Button onClick={save} disabled={saving}>
              {saving && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              {Number(quantity) < trade.open_quantity ? "Partial Close" : "Close Trade"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
