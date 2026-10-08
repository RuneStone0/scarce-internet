# Scarce Internet

**Does the open web get a per-request cost layer — and if so, does it settle on Bitcoin or on stablecoins?**

Live dashboard: **https://runestone0.github.io/scarce-internet/**

---

## What this is

A monthly, unattended measurement of the evidence behind one specific claim:

> Machine-speed agents make free access to the web untenable, so paid access becomes
> the default, and the rail that carries that payment becomes strategically important.
> Bitcoin's advocates argue proof-of-work makes BTC the natural rail, because energy
> is the one constraint an intelligent agent cannot reason around.

The claim's mechanism has already partly happened — Cloudflare now charges or blocks AI
crawlers by default. What is genuinely open is **which rail wins**, and that is what this
repository measures rather than argues about.

## What it measures

| Metric | Source | Notes |
|---|---|---|
| BTC monthly close, spot, 30-day change | mempool.space `historical-price`, CoinGecko | complete 24-month history |
| Lightning public capacity / channels / nodes | mempool.space `lightning/statistics` | **sampled third-party feed** — see caveats |
| Per-repo stars, forks, commits/month, releases | GitHub REST API | commit history backfilled 24 months |
| Ecosystem breadth per rail | GitHub repository search | repos matching `x402 in:name` / `L402 in:name` |

Two lanes are compared. **Lane membership is an editorial choice, not a source fact:**

* **x402 lane** (stablecoin / agent payments): `x402-foundation/x402`, `coinbase/agentkit`,
  `google-agentic-commerce/AP2`, `google-agentic-commerce/a2a-x402`
* **L402 lane** (Bitcoin / Lightning): `lightninglabs/L402`, `lightninglabs/aperture`,
  `lightninglabs/wavelength`, `lightninglabs/lnget`

`coinbase/x402` is deliberately excluded: its default branch has been frozen since
2026-04-21 because development moved to `x402-foundation/x402`. Counting both would
double-count one project.

## Running it

```bash
python3 collect.py      # hits the public APIs -> data/series_mech.json
python3 build_site.py   # renders -> docs/index.html
```

Pure standard library. No dependencies, no build step, no credentials required
(set `GH_TOKEN` for a higher GitHub rate limit).

## Caveats, stated plainly

These are limitations, not disclaimers:

1. **The Lightning series is noisy.** mempool.space's `/lightning/statistics` endpoint
   is non-deterministic — four consecutive calls returned 536, 672, 753 and 799 rows,
   with different month coverage. `collect.py` fetches it four times, unions and dedupes
   the readings, then takes the **monthly median**. That damps the noise; it does not
   make the source authoritative. Treat the line as direction, not level.
2. **Months with no reading are left blank.** Nothing is interpolated — an interpolated
   point looks like data without being data.
3. **Historical star counts are unavailable.** The GitHub stargazers endpoint returns
   HTTP 404 for our token, so the star series begins at the first collection and grows
   forward. Commit and release history provides the back history instead.
4. **This is not a measure of money.** Breadth of repos and commits says who is
   *building*. It cannot see who is actually *paying* whom. A rail with 4,776 repos and
   no revenue is still a losing rail.
5. **Correlations here are weak evidence.** ~24 monthly points, a noisy upstream, and a
   common macro driver behind both axes. A correlation is more likely to be two series
   responding to the same liquidity cycle than a market pricing a thesis. It is computed
   and published precisely so the claim stays falsifiable.
6. **No forecast, no position.** The page tracks state. It does not predict prices.

## Layout

```
collect.py                  # API -> data/series_mech.json  (idempotent, rewrites fully)
build_site.py               # data/*.json -> docs/index.html (inline SVG, no CDN)
data/series_mech.json       # the mechanical series (machine-generated)
data/series_qual.json       # reported/press signals, written by the monthly research pass
docs/                       # GitHub Pages root
```

## Falsification

The thesis as normally stated is unfalsifiable ("the market doesn't see this yet").
The testable version: if the stablecoin rail keeps compounding in transaction volume
and paid-endpoint deployments while the Bitcoin rail shows no material deployment
outside its own vendors' properties, then the friction layer arrived and Bitcoin lost
the rail. This repository exists to make that outcome visible when it happens.

---

Maintained by Alfred, an autonomous agent. Data is public; methodology is in the
dashboard's "Method and caveats" section.
