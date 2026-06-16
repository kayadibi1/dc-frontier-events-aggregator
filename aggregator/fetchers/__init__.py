"""Per-source fetch adapters.

Each adapter takes a Source and returns a SourceResult carrying already-normalized
Event objects plus status/error, so the rest of the pipeline is format-agnostic.
A single source's failure is captured as an error, never an exception that aborts
the whole run.
"""

from __future__ import annotations

import asyncio

from ..config import Source
from .aisf import fetch_aisf
from .atlanticcouncil import fetch_atlanticcouncil
from .base import SourceResult
from .brookings import fetch_brookings
from .cdt import fetch_cdt
from .cnas import fetch_cnas
from .congress import fetch_congress
from .cosr import fetch_cosr
from .csis import fetch_csis
from .cset import fetch_cset
from .gtlaw import fetch_gtlaw
from .ics import fetch_ics
from .itif import fetch_itif
from .jsrender import fetch_jsrender
from .luma import fetch_luma, fetch_luma_discover
from .nasem import fetch_nasem
from .nist import fetch_nist
from .policy_ngos import (
    fetch_aei,
    fetch_bpc,
    fetch_carnegie,
    fetch_fas,
    fetch_heritage,
    fetch_hudson,
    fetch_mercatus,
    fetch_newamerica,
    fetch_rand,
    fetch_scsp,
    fetch_stimson,
    fetch_wilson,
)
from .umdcs import fetch_umdcs
from .watchlist import fetch_watchlist
from ..render import close_render

ADAPTERS = {
    "luma": fetch_luma,
    "luma-discover": fetch_luma_discover,
    "ics": fetch_ics,
    "cset": fetch_cset,
    "csis": fetch_csis,
    "brookings": fetch_brookings,
    "cnas": fetch_cnas,
    "atlanticcouncil": fetch_atlanticcouncil,
    "nist": fetch_nist,
    "itif": fetch_itif,
    "cdt": fetch_cdt,
    "nasem": fetch_nasem,
    "hudson": fetch_hudson,
    "aei": fetch_aei,
    "bpc": fetch_bpc,
    "newamerica": fetch_newamerica,
    "heritage": fetch_heritage,
    "carnegie": fetch_carnegie,
    "rand": fetch_rand,
    "wilson": fetch_wilson,
    "scsp": fetch_scsp,
    "stimson": fetch_stimson,
    "fas": fetch_fas,
    "mercatus": fetch_mercatus,
    "umdcs": fetch_umdcs,
    "gtlaw": fetch_gtlaw,
    "congress": fetch_congress,
    "aisf": fetch_aisf,
    "cosr": fetch_cosr,
    "jsrender": fetch_jsrender,
    "watchlist": fetch_watchlist,
}


# Transient HTTP statuses worth retrying; a 4xx (404/403) or a real empty 200 is not.
TRANSIENT_STATUS = {429, 500, 502, 503, 504}
MAX_FETCH_TRIES = 3
RETRY_BACKOFF = 0.5   # seconds, doubles each retry (0.5s, 1s)


def _is_transient(res: SourceResult) -> bool:
    """A failure worth retrying: a raised exception (status is None) or a 5xx/429.
    A permanent 4xx or a genuinely empty 200 result is left as-is."""
    return res.status is None or res.status in TRANSIENT_STATUS


async def _fetch_with_retry(src: Source, fn, tries: int = MAX_FETCH_TRIES,
                            sleep=asyncio.sleep, backoff: float = RETRY_BACKOFF) -> SourceResult:
    """Run an adapter, retrying only TRANSIENT failures with exponential backoff so
    a momentary network blip doesn't drop a source for the whole 12h cycle. A
    success or a permanent failure returns immediately. Adapter crashes are caught
    (a single source must never kill the run)."""
    last: SourceResult | None = None
    for attempt in range(tries):
        try:
            res = await fn(src)
        except Exception as e:  # adapter crash must not kill the run
            res = SourceResult(src, [], None, repr(e))
        if res.ok or not _is_transient(res):
            return res
        last = res
        if attempt < tries - 1:
            await sleep(backoff * (2 ** attempt))
    return last


async def gather_all(sources: list[Source]) -> list[SourceResult]:
    async def one(src: Source) -> SourceResult:
        fn = ADAPTERS.get(src.kind)
        if fn is None:
            return SourceResult(src, [], None, f"no adapter for kind={src.kind!r}")
        return await _fetch_with_retry(src, fn)

    try:
        return list(await asyncio.gather(*[one(s) for s in sources]))
    finally:
        await close_render()    # close the shared headless browser in this same loop
