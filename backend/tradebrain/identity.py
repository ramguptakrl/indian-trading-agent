"""Security identity primitives for Indian markets.

Trade Brain treats exchange symbols as listings, not issuer identity. ISIN is the
cross-exchange security key; issuer/company identity sits above it. This module is a
small compatibility foundation for the future official NSE/BSE security master.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal


class ExchangeListing(BaseModel):
    exchange: Literal["NSE", "BSE"]
    symbol: str = Field(min_length=1)
    isin: str | None = None
    issuer_entity_id: str | None = None


def normalize_isin(isin: str | None) -> str | None:
    if not isin:
        return None
    value = isin.strip().upper()
    if value in {"NA", "N/A", "NONE", "NULL", "-"}:
        return None
    return value


def validate_listing_identity(listing: ExchangeListing) -> dict:
    isin = normalize_isin(listing.isin)
    warnings: list[str] = []
    if isin is None:
        warnings.append(
            "Listing has no verified ISIN; do not cross-merge it with another exchange listing by company-name similarity"
        )
    elif len(isin) != 12:
        warnings.append("ISIN is not 12 characters; treat identity as unverified")

    return {
        "exchange": listing.exchange,
        "symbol": listing.symbol.strip().upper(),
        "isin": isin,
        "issuer_entity_id": listing.issuer_entity_id,
        "cross_exchange_merge_key": isin if isin and len(isin) == 12 else None,
        "identity_verified_for_merge": bool(isin and len(isin) == 12),
        "warnings": warnings,
    }


def can_merge_listings(a: ExchangeListing, b: ExchangeListing) -> bool:
    """Only a matching valid ISIN is enough for automatic cross-exchange merge."""

    a_isin = normalize_isin(a.isin)
    b_isin = normalize_isin(b.isin)
    return bool(
        a_isin
        and b_isin
        and len(a_isin) == 12
        and len(b_isin) == 12
        and a_isin == b_isin
    )
