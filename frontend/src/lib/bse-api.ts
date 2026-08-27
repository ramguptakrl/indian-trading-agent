const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function bseFetch<T = any>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...options?.headers },
    });
  } catch {
    throw new Error(`Cannot connect to Trade Brain backend at ${API_BASE}.`);
  }

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {}
    throw new Error(detail);
  }
  return response.json();
}

export const getBseEvidenceBaseline = () =>
  bseFetch(`/api/tradebrain/evidence/latest/NSE/BSE`);

export const buildBseEvidenceBaseline = () =>
  bseFetch(`/api/tradebrain/evidence/baseline/NSE/BSE?intraday_interval=5m&persist=true`);

export const getBseProspectiveGapObservations = () =>
  bseFetch(`/api/tradebrain/evidence/prospective-gap-001/observations/NSE/BSE`);

export const getBseFocusLabStats = () =>
  bseFetch(`/api/tradebrain/focus-lab/stats`);

export const getBseChallengerStats = () =>
  bseFetch(`/api/tradebrain/challengers/stats/summary`);

export const getBseEvidenceDoctrine = () =>
  bseFetch(`/api/tradebrain/evidence/doctrine`);

export const getBseActualTradeStats = () =>
  bseFetch(`/api/tradebrain/actual-trades/stats`);
