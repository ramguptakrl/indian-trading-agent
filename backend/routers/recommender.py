"""Recommendation Engine API — combines strategies into ranked soft evidence."""

from fastapi import APIRouter, Query
from backend.recommender import recommend, _analyze_stock
from backend.tradebrain.soft_evidence import annotate_recommendation_payload

router = APIRouter(prefix="/api/recommend", tags=["recommend"])


@router.get("/")
def get_recommendations(
    universe: str = Query("nifty100", description="nifty50, nifty100, or bse250"),
    min_signals: int = Query(2, description="Min aligned signals to recommend"),
):
    """Get ranked research ideas.

    Existing response fields are preserved for frontend compatibility. Trade Brain
    annotations make clear that score-derived probabilities are heuristic soft evidence,
    not learned success odds or trade authorization.
    """
    return annotate_recommendation_payload(recommend(universe, min_signals))


@router.get("/stock/{ticker}")
def analyze_single_stock(ticker: str):
    """Get a soft-evidence recommendation for a single stock."""
    result = _analyze_stock(ticker)
    if not result:
        return {"error": f"Could not analyze {ticker}"}
    return annotate_recommendation_payload(result)
