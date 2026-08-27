const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function getPositionGuardian() {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/tradebrain/actual-trades/guardian`, {
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
    });
  } catch {
    throw new Error(`Cannot connect to backend at ${API_BASE}. Is it running?`);
  }
  if (!res.ok) throw new Error(`Guardian API error: ${res.status} ${res.statusText}`);
  return res.json();
}
