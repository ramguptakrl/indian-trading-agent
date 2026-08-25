"use client";

import { useState } from "react";
import { updatePnL } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loader2, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

interface Props {
  open: boolean;
  onClose: () => void;
  taskId: string;
  ticker: string;
  signal: string;
  onSaved: () => void;
}

export function PnLDialog({ open, onClose, taskId, signal, onSaved }: Props) {
  const [entryPrice, setEntryPrice] = useState("");
  const [exitPrice, setExitPrice] = useState("");
  const [saving, setSaving] = useState(false);

  const handleSaveOpen = async () => {
    const entry = parseFloat(entryPrice);
    if (isNaN(entry) || entry <= 0) return toast.error("Enter a valid entry price");
    setSaving(true);
    try {
      await updatePnL(taskId, { entry_price: entry } as any);
      toast.success(`BSE research outcome marked OPEN at ₹${entry}`);
      onSaved();
      onClose();
      setEntryPrice("");
      setExitPrice("");
    } catch (e: any) {
      toast.error(e.message || "Failed to save observed outcome");
    } finally {
      setSaving(false);
    }
  };

  const handleSave = async () => {
    const entry = parseFloat(entryPrice);
    const exit = parseFloat(exitPrice);
    if (isNaN(entry) || isNaN(exit) || entry <= 0 || exit <= 0) return toast.error("Enter valid prices");
    setSaving(true);
    try {
      const result: any = await updatePnL(taskId, {
        entry_price: entry,
        exit_price: exit,
        reflect: false,
      });
      toast.success(`Observed BSE outcome saved: ${result.pnl_pct >= 0 ? "+" : ""}${result.pnl_pct}%`);
      onSaved();
      onClose();
      setEntryPrice("");
      setExitPrice("");
    } catch (e: any) {
      toast.error(e.message || "Failed to save observed outcome");
    } finally {
      setSaving(false);
    }
  };

  const entry = parseFloat(entryPrice);
  const exit = parseFloat(exitPrice);
  const pnlPct = !isNaN(entry) && !isNaN(exit) && entry > 0 ? ((exit - entry) / entry) * 100 : null;
  const isShort = ["SHORT_CANDIDATE", "SHORT", "SELL", "UNDERWEIGHT"].includes(signal.toUpperCase());
  const effectivePnl = pnlPct !== null ? (isShort ? -pnlPct : pnlPct) : null;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Observed BSE Research Outcome</DialogTitle>
          <p className="text-xs text-muted-foreground">
            Research label: <span className="font-semibold">{signal}</span> ({isShort ? "short direction" : "long direction"}).
            This is not the Actual Trades journal.
          </p>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <label className="text-xs font-medium mb-1 block">Observed Entry Price (₹)</label>
            <Input type="number" step="0.01" value={entryPrice} onChange={(e) => setEntryPrice(e.target.value)} autoFocus />
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">Observed Exit Price (₹)</label>
            <Input type="number" step="0.01" value={exitPrice} onChange={(e) => setExitPrice(e.target.value)} />
          </div>

          {effectivePnl !== null && (
            <div className={`p-3 rounded-lg ${effectivePnl >= 0 ? "bg-green-50 border border-green-200" : "bg-red-50 border border-red-200"}`}>
              <p className="text-xs text-muted-foreground">Observed directional P&L</p>
              <p className={`text-xl font-bold ${effectivePnl >= 0 ? "text-green-700" : "text-red-700"}`}>
                {effectivePnl >= 0 ? "+" : ""}{effectivePnl.toFixed(2)}%
              </p>
            </div>
          )}

          <div className="flex items-start gap-2 rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
            <ShieldCheck className="h-4 w-4 shrink-0" />
            <span>
              This legacy observed-outcome field is kept for research history only. It does not automatically train/promote Trade Brain parameters. Canonical learning uses audited replay, prospective evidence and the separate Actual Trades journal.
            </span>
          </div>

          <div className="flex gap-2 justify-end flex-wrap">
            <Button variant="outline" onClick={onClose} disabled={saving}>Cancel</Button>
            <Button variant="outline" onClick={handleSaveOpen} disabled={saving || !entryPrice}>
              {saving ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null} Mark as Open
            </Button>
            <Button onClick={handleSave} disabled={saving || !entryPrice || !exitPrice}>
              {saving ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null} Save Observed Outcome
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
