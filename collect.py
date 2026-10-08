#!/usr/bin/env python3
"""Scarce-internet trend collector — every number here is stated by a public API.

Thesis under test: the open web will acquire a per-request cost layer because
machine-speed volume makes free access untenable. The open question is whether that
rail settles in BITCOIN (L402 / Lightning) or in STABLECOINS (x402 / USDC).

This module owns ONLY mechanical metrics. Anything reported in prose (x402
transaction counts, foundation membership, policy changes) is written by the
qualitative research pass into data/series_qual.json and is never touched here.

Output: data/series_mech.json
    {"generated_at", "lane_membership", "sources", "months": {"YYYY-MM": {...}}}

Idempotent: the mechanical series is fully derived, so every run rewrites it. A
source that fails is recorded as `degraded` and its metric is carried forward from
the previous file rather than silently becoming null.

Usage:  python3 collect.py [--out DIR]
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data"
OUT_FILE = OUT_DIR / "series_mech.json"

MONTHS_BACK = 24
UA = "scarce-internet-collector/1.0 (+https://github.com/RuneStone0/scarce-internet)"
TIMEOUT = 30
COMMIT_PAGE_CAP = 2          # paginate at most 2x100 commits per repo-month

# Lane membership is an editorial choice, NOT a source fact — labelled as such in
# every output. x402 lane = stablecoin / agent-payment rails; L402 lane = Bitcoin.
#
# coinbase/x402 is deliberately EXCLUDED from the x402 lane: its default branch has
# been frozen since 2026-04-21 ("chore: bump main to match foundation repo") because
# development moved to x402-foundation/x402. Counting both double-counts the project.
LANE_X402 = [
    "x402-foundation/x402",
    "coinbase/agentkit",
    "google-agentic-commerce/AP2",
    "google-agentic-commerce/a2a-x402",
]
LANE_L402 = [
    "lightninglabs/L402",
    "lightninglabs/aperture",
    "lightninglabs/wavelength",
    "lightninglabs/lnget",
]
ALL_REPOS = LANE_X402 + LANE_L402

# Ecosystem breadth: how many distinct repos exist per lane name. Four flagship repos
# can all be alive while one rail has no ecosystem at all, so breadth is the closest
# thing to a "this is becoming real" measure a public API will state.
ECOSYSTEM_QUERIES = {"x402": "x402+in:name", "l402": "l402+in:name"}

# NOTE 2026-10-08: /repos/{o}/{r}/stargazers returns HTTP 404 for this token even
# though /repos/{o}/{r} and /user succeed, so historical star counts are NOT
# available. Stars are tracked forward-only from the first collection. Do not
# re-attempt stargazer pagination without re-testing the endpoint.
# Likewise /stats/commit_activity answered 202/empty for x402-foundation/x402, so
# per-month commit counts are derived from the commits endpoint instead (slow but
# deterministic) — a degraded stats call would otherwise silently zero the biggest
# repo in the x402 lane and invert the lane comparison.


# ---------------------------------------------------------------- helpers

def _load_env() -> None:
    for p in ("/opt/data/.env", "/opt/data/profiles/alfred/.env"):
        if not os.path.exists(p):
            continue
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def get_json(url: str, headers: dict | None = None, retries: int = 3):
    """GET -> parsed JSON. Backs off on rate limits; raises after the last attempt."""
    last: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(url)
        req.add_header("User-Agent", UA)
        req.add_header("Accept", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as f:
                return json.load(f)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 429) and attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            if e.code >= 500 and attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise
        except Exception as e:                     # noqa: BLE001 - network flake
            last = e
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    raise last  # pragma: no cover


def month_key(d) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_range(n_back: int) -> list[str]:
    today = dt.datetime.now(dt.timezone.utc).date().replace(day=1)
    out, y, m = [], today.year, today.month
    for _ in range(n_back + 1):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return sorted(out)


def month_bounds(mk: str) -> tuple[int, int]:
    """(first second, last second) of the month, UTC."""
    y, m = (int(x) for x in mk.split("-"))
    start = dt.datetime(y, m, 1, tzinfo=dt.timezone.utc)
    nxt = dt.datetime(y + 1, 1, 1, tzinfo=dt.timezone.utc) if m == 12 \
        else dt.datetime(y, m + 1, 1, tzinfo=dt.timezone.utc)
    return int(start.timestamp()), int(nxt.timestamp()) - 1


def median(xs: list) -> float | None:
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    if not xs:
        return None
    n = len(xs)
    mid = n // 2
    return float(xs[mid]) if n % 2 else (xs[mid - 1] + xs[mid]) / 2


# ---------------------------------------------------------------- sources

def fetch_btc(sources: dict) -> dict:
    """Monthly close from mempool.space historical-price; spot + 30d change from CoinGecko."""
    out: dict = {}
    for mk in month_range(MONTHS_BACK):
        try:
            _, end = month_bounds(mk)
            d = get_json(
                "https://mempool.space/api/v1/historical-price"
                f"?currency=USD&timestamp={end}"
            )
            px = (d.get("prices") or [{}])[0].get("USD")
            if px:
                out[mk] = {"btc_close_usd": float(px)}
        except Exception as e:                     # noqa: BLE001
            sources[f"btc_close:{mk}"] = f"degraded: {e}"
    this_mk = month_key(dt.datetime.now(dt.timezone.utc).date())
    try:
        spot = get_json(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        )
        out.setdefault(this_mk, {})["btc_spot_usd"] = float(spot["bitcoin"]["usd"])
    except Exception as e:                         # noqa: BLE001
        sources["btc_spot"] = f"degraded: {e}"
    try:
        mc = get_json(
            "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
            "?vs_currency=usd&days=365&interval=daily"
        )
        prices = mc.get("prices") or []
        if len(prices) > 31 and prices[-31][1]:
            out.setdefault(this_mk, {})["btc_chg_30d_pct"] = round(
                (prices[-1][1] - prices[-31][1]) / prices[-31][1] * 100, 2
            )
    except Exception as e:                         # noqa: BLE001
        sources["btc_chg_30d"] = f"degraded: {e}"
    sources["btc"] = "mempool.space historical-price + CoinGecko simple/market_chart"
    return out


def fetch_lightning(sources: dict) -> dict:
    """Lightning public-graph capacity / channels / nodes, MEDIAN of a unioned sample set.

    Two problems with this source, both measured on 2026-10-08, both handled here:

    1. NON-DETERMINISM. /lightning/statistics/3y returned 536, 672, 753 and 799 rows on
       four consecutive calls, with wildly different month coverage — it is a sampled,
       load-balanced cache, so a single fetch yields an arbitrary subset and would make
       the monthly figure jitter for reasons that have nothing to do with Lightning.
       Fixed by fetching it LN_FETCHES times, unioning every row, and taking the monthly
       median of the union (records are deduplicated by timestamp).
    2. GAPS. Whole months can be absent from every fetch. Those stay absent — an
       interpolated point would look like data without being data.

    The level is a third-party estimate of the PUBLIC graph only; read the plotted line
    as a trend, not as the network's true capacity.
    """
    LN_FETCHES = 4
    raw: dict[int, dict] = {}
    for _ in range(LN_FETCHES):
        for iv in ("3y", "3m"):
            try:
                got = get_json(f"https://mempool.space/api/v1/lightning/statistics/{iv}")
            except Exception as e:                 # noqa: BLE001
                sources[f"lightning:{iv}"] = f"degraded: {e}"
                continue
            if isinstance(got, list):
                for r in got:
                    if r.get("added"):
                        raw[int(r["added"])] = r        # dedupe by timestamp

    samples: dict[str, dict[str, list]] = {}
    for ts, r in raw.items():
        d = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()
        mk = month_key(d)
        slot = samples.setdefault(mk, {"cap": [], "chan": [], "nodes": [], "ts": []})
        if r.get("total_capacity"):
            slot["cap"].append(r["total_capacity"])
        if r.get("channel_count"):
            slot["chan"].append(r["channel_count"])
        nodes = (r.get("clearnet_nodes") or 0) + (r.get("tor_nodes") or 0)
        if nodes:
            slot["nodes"].append(nodes)
        slot["ts"].append(ts)

    horizon = month_range(MONTHS_BACK)[0]
    out: dict = {}
    for mk, s in samples.items():
        if mk < horizon or not s["cap"]:
            continue
        out[mk] = {
            "ln_capacity_sats": int(median(s["cap"])),
            "ln_channels": int(median(s["chan"])) if s["chan"] else None,
            "ln_nodes": int(median(s["nodes"])) if s["nodes"] else None,
            "ln_samples": len(s["cap"]),
            "ln_asof": dt.datetime.fromtimestamp(max(s["ts"]), dt.timezone.utc).date().isoformat(),
            "ln_note": "mempool.space monthly median over unioned sample set; public graph only",
        }
    sources["lightning"] = (
        f"mempool.space lightning/statistics x{LN_FETCHES} unioned, deduped -> "
        f"{len(raw)} unique readings; {len(out)} month(s) covered by monthly median"
    )
    return out


def gh_headers() -> dict:
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    h = {"Accept": "application/vnd.github+json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def fetch_repos(sources: dict) -> dict:
    """Per-repo current state + a deterministic per-month commit history + releases."""
    out: dict = {}
    h = gh_headers()
    since30 = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    months = month_range(MONTHS_BACK)

    for repo in ALL_REPOS:
        rec: dict = {}
        try:
            d = get_json(f"https://api.github.com/repos/{repo}", headers=h)
            rec.update(
                stars=d.get("stargazers_count"),
                forks=d.get("forks_count"),
                open_issues=d.get("open_issues_count"),
                last_push=(d.get("pushed_at") or "")[:10],
                created=(d.get("created_at") or "")[:10],
                archived=bool(d.get("archived")),
            )
        except Exception as e:                     # noqa: BLE001
            sources[f"repo:{repo}"] = f"degraded: {e}"
            continue

        try:
            c = get_json(
                f"https://api.github.com/repos/{repo}/commits?since={since30}&per_page=100",
                headers=h,
            )
            n = len(c) if isinstance(c, list) else 0
            rec["commits_30d"] = n
            rec["commits_30d_capped"] = n >= 100
        except Exception as e:                     # noqa: BLE001
            sources[f"commits_30d:{repo}"] = f"degraded: {e}"

        by_month: dict[str, int] = {}
        for mk in months:
            start, end = month_bounds(mk)
            if start > int(time.time()):
                continue
            total = 0
            for page in range(1, COMMIT_PAGE_CAP + 1):
                try:
                    got = get_json(
                        f"https://api.github.com/repos/{repo}/commits"
                        f"?since={dt.datetime.fromtimestamp(start, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
                        f"&until={dt.datetime.fromtimestamp(end, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
                        f"&per_page=100&page={page}",
                        headers=h,
                    )
                except Exception as e:             # noqa: BLE001
                    sources[f"commits:{repo}:{mk}"] = f"degraded: {e}"
                    break
                if not isinstance(got, list) or not got:
                    break
                total += len(got)
                if len(got) < 100:
                    break
            by_month[mk] = total
        rec["commits_by_month"] = by_month

        try:
            rel = get_json(
                f"https://api.github.com/repos/{repo}/releases?per_page=100", headers=h
            )
            dates = sorted(
                r.get("published_at") for r in (rel or []) if r.get("published_at")
            )
            rec["releases_cum_by_month"] = {
                mk: sum(
                    1
                    for s in dates
                    if dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
                    <= dt.datetime.fromtimestamp(month_bounds(mk)[1], dt.timezone.utc)
                )
                for mk in months
            }
            rec["releases_total"] = len(dates)
        except Exception as e:                     # noqa: BLE001
            sources[f"releases:{repo}"] = f"degraded: {e}"

        out[repo] = rec

    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    sources["github"] = "api.github.com (authenticated)" if tok else "api.github.com (anonymous)"
    return out


def fetch_ecosystem(sources: dict) -> dict:
    """Repo count + top repo per lane name (2 search calls; search caps at 30 req/min)."""
    out: dict = {}
    h = gh_headers()
    for lane, q in ECOSYSTEM_QUERIES.items():
        try:
            d = get_json(
                f"https://api.github.com/search/repositories"
                f"?q={q}&sort=stars&order=desc&per_page=1",
                headers=h,
            )
            out[f"{lane}_ecosystem_repos"] = d.get("total_count")
            items = d.get("items") or []
            top = items[0] if items else {}
            out[f"{lane}_ecosystem_top_repo"] = top.get("full_name")
            out[f"{lane}_ecosystem_top_stars"] = top.get("stargazers_count")
        except Exception as e:                     # noqa: BLE001
            sources[f"ecosystem:{lane}"] = f"degraded: {e}"
    sources["ecosystem"] = "api.github.com search/repositories (q='<lane> in:name')"
    return out


# ---------------------------------------------------------------- assemble

def build_lane_rollups(months: dict) -> None:
    """Composite per-lane totals + rail-share ratios.

    Two shares, because they answer different questions:
      - commit share (24 months of real history)  -> who is BUILDING
      - star share   (forward-only, from run #1)  -> who is WATCHING
    """
    for mk, slot in months.items():
        reps = slot.get("repos") or {}
        sx = sum((reps.get(r) or {}).get("stars") or 0 for r in LANE_X402)
        sl = sum((reps.get(r) or {}).get("stars") or 0 for r in LANE_L402)
        if sx or sl:
            slot["x402_lane_stars"] = sx
            slot["l402_lane_stars"] = sl
            slot["l402_star_share_pct"] = round(sl / (sx + sl) * 100, 2)

        hist = slot.get("commits_hist") or {}
        if hist:
            cx = sum(int(hist.get(r) or 0) for r in LANE_X402)
            cl = sum(int(hist.get(r) or 0) for r in LANE_L402)
            slot["x402_commits_month"] = cx
            slot["l402_commits_month"] = cl
            if cx + cl:
                slot["l402_commit_share_pct"] = round(cl / (cx + cl) * 100, 2)
            # Raw commit volume is dominated by whichever single repo is busiest
            # (lightninglabs/wavelength ran 150-425 commits/month on its own), so it is
            # NOT a rail-share measure. Count ACTIVE repos instead: how many repos in
            # each lane produced at least one commit that month. That is immune to one
            # repo's volume and is the honest breadth comparison.
            ax = sum(1 for r in LANE_X402 if int(hist.get(r) or 0) > 0)
            al = sum(1 for r in LANE_L402 if int(hist.get(r) or 0) > 0)
            slot["x402_active_repos"] = ax
            slot["l402_active_repos"] = al
            if ax + al:
                slot["l402_active_share_pct"] = round(al / (ax + al) * 100, 2)


def main() -> int:
    global OUT_DIR, OUT_FILE
    argv = sys.argv[1:]
    if "--out" in argv:
        OUT_DIR = Path(argv[argv.index("--out") + 1])
        OUT_FILE = OUT_DIR / "series_mech.json"

    _load_env()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sources: dict = {}
    months = {mk: {} for mk in month_range(MONTHS_BACK)}

    btc = fetch_btc(sources)
    ln = fetch_lightning(sources)
    repos = fetch_repos(sources)
    eco = fetch_ecosystem(sources)

    prev = {}
    if OUT_FILE.exists():
        try:
            prev = (json.loads(OUT_FILE.read_text()) or {}).get("months", {})
        except Exception:                          # noqa: BLE001
            prev = {}

    for mk in months:
        months[mk].update(btc.get(mk, {}))
        months[mk].update(ln.get(mk, {}))

    now_mk = month_key(dt.datetime.now(dt.timezone.utc).date())
    months[now_mk]["repos"] = {
        r: {k: v for k, v in rec.items()
            if k not in ("commits_by_month", "releases_cum_by_month")}
        for r, rec in repos.items()
    }
    months[now_mk].update(eco)
    for repo, rec in repos.items():
        for mk, n in (rec.get("commits_by_month") or {}).items():
            if mk in months:
                months[mk].setdefault("commits_hist", {})[repo] = n
        for mk, n in (rec.get("releases_cum_by_month") or {}).items():
            if mk in months:
                months[mk].setdefault("releases_cum", {})[repo] = n

    # carry forward anything a degraded source failed to supply this run
    carried = 0
    for mk in months:
        for key, val in (prev.get(mk) or {}).items():
            if key in ("repos", "commits_hist", "releases_cum"):
                continue
            if months[mk].get(key) is None:
                months[mk][key] = val
                carried += 1
    if carried:
        sources["carry_forward"] = f"{carried} value(s) carried from the previous run"

    build_lane_rollups(months)

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "lane_membership": {
            "x402": LANE_X402, "l402": LANE_L402,
            "note": "lane assignment is editorial, not a source fact",
        },
        "sources": sources,
        "months": {k: months[k] for k in sorted(months)},
    }
    tmp = OUT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(OUT_FILE)

    degraded = {k: v for k, v in sources.items() if str(v).startswith("degraded")}
    print(f"[collect] {OUT_FILE} months={len(months)} repos={len(repos)} "
          f"degraded={len(degraded)} carried={carried}")
    for k, v in degraded.items():
        print(f"[collect] DEGRADED {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
