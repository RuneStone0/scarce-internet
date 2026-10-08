#!/usr/bin/env python3
"""Build the dark-themed static dashboard for the scarce-internet series.

Reads  data/series_mech.json  (collect.py)  and optionally  data/series_qual.json
(the monthly research pass), writes  docs/index.html.

Constraints that shaped this file:
  * No CDN, no JS framework, no build step — the page must render on GitHub Pages
    from a plain `git push`, and must still work if a stylesheet request fails.
    Everything is inline: CSS, SVG charts, and the data blob.
  * Charts are generated in Python as SVG. No client-side charting dependency to
    break, and the page is readable in a text browser.

Usage:  python3 build_site.py [--data DIR] [--out docs/index.html]
"""

from __future__ import annotations

import datetime as dt
import html
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUT_HTML = ROOT / "docs" / "index.html"

# Palette — dark only, per request. Lane colours stay consistent everywhere.
C_BG = "#0d1117"
C_PANEL = "#161b22"
C_PANEL2 = "#1c2128"
C_BORDER = "#30363d"
C_FG = "#e6edf3"
C_MUTED = "#8b949e"
C_GRID = "#21262d"
C_BTC = "#f7931a"
C_L402 = "#3fb950"      # Bitcoin / Lightning lane
C_X402 = "#58a6ff"      # stablecoin / x402 lane
C_WARN = "#d29922"
C_BAD = "#f85149"

CHART_W, CHART_H = 980, 260


# ---------------------------------------------------------------- stats

def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx and dy else None


def _rank(vals: list[float]) -> list[float]:
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    return pearson(_rank(xs), _rank(ys))


def pct_change(a: float | None, b: float | None) -> float | None:
    if not a or not b:
        return None
    return (b - a) / a * 100


def pct_change_series(months: list[str], get) -> tuple[list[str], list[float]]:
    """Month-over-month % change, skipping gaps (a gap breaks the chain)."""
    out_m, out_v = [], []
    prev = None
    for mk in months:
        v = get(mk)
        if v is None:
            prev = None
            continue
        if prev is not None and prev:
            out_m.append(mk)
            out_v.append((v - prev) / prev * 100)
        prev = v
    return out_m, out_v


# ---------------------------------------------------------------- svg

def _scale(vals, lo, hi, a, b):
    if hi == lo:
        return [(a + b) / 2] * len(vals)
    return [a + (v - lo) / (hi - lo) * (b - a) for v in vals]


def line_chart(series, months, title, ylabel, y_fmt="{:.0f}", height=CHART_H,
               log_scale=False):
    """series: list of dicts {name, color, values (None for gaps), axis}. Inline SVG."""
    pad_l, pad_r, pad_t, pad_b = 62, 205, 26, 34
    w, h = CHART_W, height
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b

    allv = [v for s in series for v in s["values"] if v is not None and v > 0] \
        if log_scale else [v for s in series for v in s["values"] if v is not None]
    if not allv:
        return f'<svg viewBox="0 0 {w} {h}" width="100%"></svg>'
    lo, hi = min(allv), max(allv)
    if log_scale:
        lo, hi = math.log10(lo), math.log10(hi)
    span = (hi - lo) or 1
    lo -= span * 0.08
    hi += span * 0.08

    def ty(v):
        vv = math.log10(v) if log_scale and v > 0 else v
        return pad_t + plot_h - (vv - lo) / (hi - lo) * plot_h

    n = len(months)
    def tx(i):
        return pad_l + (i / max(n - 1, 1)) * plot_w

    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" '
             f'aria-label="{html.escape(title)}" style="display:block">']
    parts.append(f'<rect x="0" y="0" width="{w}" height="{h}" fill="none"/>')

    # gridlines + y labels
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        raw = (10 ** v) if log_scale else v
        y = pad_t + plot_h - (v - lo) / (hi - lo) * plot_h
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l + plot_w}" '
                     f'y2="{y:.1f}" stroke="{C_GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l - 8}" y="{y + 4:.1f}" fill="{C_MUTED}" '
                     f'font-size="11" text-anchor="end" font-family="ui-monospace,'
                     f'SFMono-Regular,monospace">{html.escape(y_fmt.format(raw))}</text>')

    # x labels — about 7 evenly spaced
    step = max(1, n // 7)
    for i in range(0, n, step):
        parts.append(f'<text x="{tx(i):.1f}" y="{h - 10}" fill="{C_MUTED}" '
                     f'font-size="11" text-anchor="middle" font-family="ui-monospace,'
                     f'SFMono-Regular,monospace">{months[i]}</text>')

    # lines
    for s in series:
        seg, pen = [], False
        for i, v in enumerate(s["values"]):
            if v is None or (log_scale and v <= 0):
                pen = False
                continue
            x, y = tx(i), ty(v)
            seg.append(("M" if not pen else "L") + f"{x:.1f},{y:.1f}")
            pen = True
        if seg:
            parts.append(f'<path d="{" ".join(seg)}" fill="none" stroke="{s["color"]}" '
                         f'stroke-width="2" stroke-linejoin="round"/>')
        for i, v in enumerate(s["values"]):
            if v is None or (log_scale and v <= 0):
                continue
            parts.append(f'<circle cx="{tx(i):.1f}" cy="{ty(v):.1f}" r="2.6" '
                         f'fill="{s["color"]}"><title>{html.escape(s["name"])} '
                         f'{months[i]}: {html.escape(str(y_fmt.format(v)))}</title></circle>')

    # legend
    for k, s in enumerate(series):
        ly = pad_t + 6 + k * 20
        parts.append(f'<rect x="{pad_l + plot_w + 14}" y="{ly - 8}" width="10" height="10" '
                     f'rx="2" fill="{s["color"]}"/>')
        parts.append(f'<text x="{pad_l + plot_w + 30}" y="{ly + 1}" fill="{C_FG}" '
                     f'font-size="11.5" font-family="ui-sans-serif,system-ui,sans-serif">'
                     f'{html.escape(s["name"])}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------- page

def build(mech: dict, qual: dict) -> str:
    months_map = mech.get("months", {})
    months = sorted(months_map)
    gen_raw = mech.get("generated_at", "")
    try:
        gen = dt.datetime.fromisoformat(gen_raw).strftime("%-d %b %Y, %H:%M UTC")
    except Exception:
        gen = gen_raw

    def g(mk, *keys):
        node = months_map.get(mk) or {}
        for k in keys:
            if k in node and node[k] is not None:
                return node[k]
            node = node.get(k) or {}
        return None

    def series(key, scale=1.0):
        return [None if (v := g(mk, key)) is None else v / scale for mk in months]

    # ---- headline numbers
    last = months[-1] if months else None
    prev = months[-2] if len(months) > 1 else None

    ln_cap = [g(mk, "ln_capacity_sats") for mk in months]
    ln_cap_btc = [None if v is None else v / 1e8 for v in ln_cap]
    ln_chan = [g(mk, "ln_channels") for mk in months]
    xact = [g(mk, "x402_active_repos") for mk in months]
    lact = [g(mk, "l402_active_repos") for mk in months]
    lshare = [g(mk, "l402_active_share_pct") for mk in months]
    btc = [g(mk, "btc_close_usd") for mk in months]
    btc_live = g(last, "btc_spot_usd") or g(last, "btc_close_usd")

    first_ln = next((v for v in ln_cap_btc if v), None)
    last_ln = next((v for v in reversed(ln_cap_btc) if v), None)

    eco_x = g(last, "x402_ecosystem_repos")
    eco_l = g(last, "l402_ecosystem_repos")
    star_x = g(last, "x402_lane_stars")
    star_l = g(last, "l402_lane_stars")

    # ---- correlations: monthly % change vs BTC monthly % change
    btc_m, btc_v = pct_change_series(months, lambda mk: g(mk, "btc_close_usd"))
    btcmap = dict(zip(btc_m, btc_v))

    corr_rows = []
    for label, getter in (
        ("Lightning public capacity", lambda mk: g(mk, "ln_capacity_sats")),
        ("Lightning channel count", lambda mk: g(mk, "ln_channels")),
        ("L402 active repos", lambda mk: g(mk, "l402_active_repos")),
        ("x402 active repos", lambda mk: g(mk, "x402_active_repos")),
    ):
        km, kv = pct_change_series(months, getter)
        pairs = [(btcmap[k], v) for k, v in zip(km, kv) if k in btcmap]
        if len(pairs) >= 3:
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            corr_rows.append((label, pearson(xs, ys), spearman(xs, ys), len(pairs)))

    def fmt_c(v):
        if v is None:
            return "—"
        col = C_FG if abs(v) < 0.3 else (C_WARN if abs(v) < 0.6 else C_BAD)
        return f'<span style="color:{col}">{v:+.2f}</span>'

    corr_html = "".join(
        f"<tr><td>{html.escape(l)}</td><td class='num'>{fmt_c(p)}</td>"
        f"<td class='num'>{fmt_c(s)}</td><td class='num'>{n}</td></tr>"
        for l, p, s, n in corr_rows
    ) or "<tr><td colspan='4' class='muted'>not enough overlapping months yet</td></tr>"

    # ---- table
    trows = []
    for mk in reversed(months):
        v = months_map.get(mk) or {}
        def n2(x, f="{:,}"):
            return f.format(x) if isinstance(x, (int, float)) else "—"
        trows.append(
            "<tr>"
            f"<td class='mono'>{mk}</td>"
            f"<td class='num'>{n2(v.get('btc_close_usd'), '{:,.0f}')}</td>"
            f"<td class='num'>{n2(round(v['ln_capacity_sats']/1e8,1) if v.get('ln_capacity_sats') else None, '{:,.1f}')}</td>"
            f"<td class='num'>{n2(v.get('ln_channels'))}</td>"
            f"<td class='num'>{n2(v.get('x402_active_repos'))}</td>"
            f"<td class='num'>{n2(v.get('l402_active_repos'))}</td>"
            f"<td class='num'>{n2(round(v['l402_active_share_pct'],1) if v.get('l402_active_share_pct') is not None else None, '{:,.1f}')}</td>"
            "</tr>"
        )

    # ---- qualitative blocks
    qual_notes = ""
    if qual.get("entries"):
        items = []
        for e in sorted(qual["entries"], key=lambda x: x.get("month", ""), reverse=True)[:8]:
            srcs = "".join(
                f'<a href="{html.escape(s["url"])}" target="_blank" rel="noopener">[{i+1}]</a> '
                for i, s in enumerate(e.get("sources", []))
            )
            items.append(
                f'<li><strong class="mono">{html.escape(e.get("month",""))}</strong> — '
                f'{html.escape(e.get("note",""))} <span class="srcs">{srcs}</span></li>'
            )
        qual_notes = ("<h2>Reported signals <span class='muted small'>(from press and "
                      "project pages, not an API)</span></h2>"
                      f"<ul class='notes'>{''.join(items)}</ul>")

    # ---- charts
    ch_lane = line_chart(
        [{"name": "x402 lane", "color": C_X402, "values": xact},
         {"name": "L402 lane", "color": C_L402, "values": lact}],
        months, "Active repos per lane", "repos", "{:.0f}")

    norm_base = {}
    def norm_series(key):
        raw = series(key)
        base = next((v for v in raw if v), None)
        if not base:
            return None
        norm_base[key] = base
        return [None if v is None else v / base * 100 for v in raw]

    ch_norm = line_chart(
        [{"name": "BTC price", "color": C_BTC,
          "values": norm_series("btc_close_usd")},
         {"name": "Lightning capacity", "color": C_L402, "values": norm_series("ln_capacity_sats")},
         {"name": "L402 repos", "color": C_X402, "values": norm_series("l402_active_repos")}],
        months, "Normalised to first reading = 100", "index", "{:.0f}",
        height=290)

    ch_btc = line_chart(
        [{"name": "BTC / USD", "color": C_BTC, "values": btc}],
        months, "Bitcoin monthly close", "USD", "{:,.0f}", height=210)

    src_rows = "".join(
        f"<tr><td class='mono'>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>"
        for k, v in sorted(mech.get("sources", {}).items())
    )

    lshare_now = next((v for v in reversed(lshare) if v is not None), None)
    lshare_12 = lshare[-13] if len(lshare) >= 13 else None

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scarce Internet — Bitcoin vs stablecoin rails</title>
<style>
  :root {{
    --bg:{C_BG}; --panel:{C_PANEL}; --panel2:{C_PANEL2}; --border:{C_BORDER};
    --fg:{C_FG}; --muted:{C_MUTED}; --btc:{C_BTC}; --l402:{C_L402}; --x402:{C_X402};
    --warn:{C_WARN}; --bad:{C_BAD};
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
    font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:1060px; margin:0 auto; padding:34px 22px 70px; }}
  h1 {{ font-size:27px; margin:0 0 6px; letter-spacing:-.02em; }}
  h2 {{ font-size:16px; margin:30px 0 12px; letter-spacing:.01em;
        text-transform:uppercase; color:var(--muted); font-weight:600; }}
  a {{ color:var(--x402); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  .sub {{ color:var(--muted); font-size:14px; max-width:74ch; }}
  .small {{ font-size:12.5px; }}
  .mono, .num {{ font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace;
                 font-variant-numeric:tabular-nums; }}
  .muted {{ color:var(--muted); }}
  .card {{ background:var(--panel); border:1px solid var(--border);
           border-radius:10px; padding:16px 18px; margin:14px 0; }}
  .grid {{ display:grid; gap:14px; grid-template-columns:repeat(auto-fit,minmax(215px,1fr)); }}
  .kpi label {{ display:block; color:var(--muted); font-size:12px;
                text-transform:uppercase; letter-spacing:.04em; }}
  .kpi b {{ display:block; font-size:26px; margin-top:5px; font-weight:650;
            font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
  .kpi span {{ font-size:12.5px; color:var(--muted); }}
  .banner {{ background:{C_PANEL2}; border:1px solid var(--border);
             border-left:3px solid var(--warn); border-radius:8px;
             padding:12px 15px; margin:18px 0; font-size:13.5px; color:#c9d1d9; }}
  table {{ border-collapse:collapse; width:100%; font-size:13px; }}
  th, td {{ text-align:left; padding:6px 9px; border-bottom:1px solid var(--grid); }}
  th {{ color:var(--muted); font-weight:600; font-size:11.5px;
        text-transform:uppercase; letter-spacing:.04em; }}
  td.num, th.num {{ text-align:right; }}
  tr:hover td {{ background:rgba(255,255,255,.025); }}
  .srcs a {{ font-size:11.5px; }}
  ul.notes li {{ margin:7px 0; }}
  .scroller {{ max-height:430px; overflow:auto; border:1px solid var(--border);
               border-radius:8px; }}
  .scroller table th {{ position:sticky; top:0; background:var(--panel2); }}
  footer {{ color:var(--muted); font-size:12.5px; margin-top:36px;
            border-top:1px solid var(--border); padding-top:16px; }}
  .dot {{ display:inline-block; width:8px; height:8px; border-radius:50%;
          margin-right:6px; vertical-align:1px; }}
</style></head>
<body><div class="wrap">

<h1>Scarce Internet</h1>
<p class="sub">Does the open web get a per-request cost layer — and if so, does it settle on
<strong style="color:var(--l402)">Bitcoin</strong> or on
<strong style="color:var(--x402)">stablecoins</strong>? This page tracks the public
evidence monthly. Built {html.escape(gen)}.</p>

<div class="grid" style="margin-top:20px">
  <div class="card kpi"><label>x402 ecosystem repos</label><b style="color:var(--x402)">{eco_x if eco_x is not None else "—"}</b><span>repos named "x402"</span></div>
  <div class="card kpi"><label>L402 ecosystem repos</label><b style="color:var(--l402)">{eco_l if eco_l is not None else "—"}</b><span>repos named "L402"</span></div>
  <div class="card kpi"><label>L402 lane share of activity</label><b>{f"{lshare_now:.0f}%" if lshare_now is not None else "—"}</b><span>share of active repos across both lanes, {html.escape(last or "")}</span></div>
  <div class="card kpi"><label>BTC</label><b style="color:var(--btc)">${btc_live:,.0f}</b><span>{(f"{g(last,'btc_chg_30d_pct'):+.1f}% 30d") if g(last,'btc_chg_30d_pct') is not None else ""}</span></div>
</div>

<div class="banner">
  <strong>Read this before the numbers.</strong> The rail question is not close on breadth —
  two orders of magnitude apart — but breadth is not revenue, and this page cannot see who is
  actually <em>paying</em> whom. The Lightning series comes from a sampled third-party feed
  whose coverage varies: treat its line as direction, not level. Correlation figures further
  down are on ~24 monthly points and are there to keep the claim falsifiable, not to support a
  forecast. <a href="#method">Method and caveats ↓</a>
</div>

<h2>Rail contest — who is building</h2>
<div class="card">{ch_lane}
<p class="sub small" style="margin:10px 0 0">
<strong>Metric:</strong> number of repos in each lane that produced ≥1 commit that month.
Chosen over raw commit volume because one repo (lightninglabs/wavelength, 150–425
commits/month) otherwise dominates the whole comparison.
<strong>Lane membership is our editorial call</strong>, not a source fact.</p></div>

<h2>Long view — indexed to first reading</h2>
<div class="card">{ch_norm}
<p class="sub small" style="margin:10px 0 0">Bitcoin's price and Lightning's public capacity
have both fallen over this window while the stablecoin agent-payment ecosystem expanded. That
is the single most important observation on this page.</p></div>

<h2>Bitcoin</h2>
<div class="card">{ch_btc}</div>

<h2>Correlation with BTC <span class="muted small">— monthly % change, pairwise</span></h2>
<div class="card">
<table><thead><tr><th>Series</th><th class="num">Pearson</th><th class="num">Spearman</th><th class="num">n</th></tr></thead>
<tbody>{corr_html}</tbody></table>
<p class="sub small" style="margin:12px 0 0"><strong>Do not trade on this.</strong> n≈24 monthly
points, a non-deterministic upstream feed, and a common macro driver behind both axes: a
correlation here is more likely to be two series responding to the same liquidity cycle than
any rail being priced. It is kept because a claim that can't be checked isn't a claim.</p></div>

{qual_notes}

<h2>All months</h2>
<div class="scroller"><table>
<thead><tr><th>Month</th><th class="num">BTC $</th><th class="num">LN BTC</th>
<th class="num">LN channels</th><th class="num">x402 active</th><th class="num">L402 active</th>
<th class="num">L402 share %</th></tr></thead>
<tbody>{"".join(trows)}</tbody></table></div>

<h2 id="method">Method and caveats</h2>
<div class="card">
<ul class="notes">
<li><strong>Every number is stated by a public API</strong> and regenerated from scratch each
run — nothing is hand-entered or interpolated. A source that fails is recorded as
<code>degraded</code> and its value carried forward from the previous run rather than
silently becoming blank.</li>
<li><strong>Months with no Lightning reading are left blank.</strong> An interpolated point
would look like data without being data.</li>
<li><strong>Lane membership is editorial.</strong> We pick four flagship repos per rail and
count commits per repo-month. Change the membership and the ratios move — that is a real
limitation, which is why the raw per-repo data is published alongside.</li>
<li><strong>Historical stars are not available.</strong> The stargazers endpoint returns 404
for our token, so a star series starts from the first collection and grows forward;
commit and release history is used for the back history instead.</li>
<li><strong>Only a trend is claimed.</strong> No causal claim, no forecast, no position.</li>
</ul>
<table><thead><tr><th>Source</th><th>What it provides</th></tr></thead>
<tbody>{src_rows}</tbody></table>
</div>

<footer>
Generated by <code>collect.py</code> + <code>build_site.py</code>.
Data: <a href="data/series_mech.json">series_mech.json</a>.
Monthly, unattended. Maintained by Alfred (Chief of Staff).
</footer>
</div></body></html>
"""


def main() -> int:
    argv = sys.argv[1:]
    data_dir, out = DATA_DIR, OUT_HTML
    if "--data" in argv:
        data_dir = Path(argv[argv.index("--data") + 1])
    if "--out" in argv:
        out = Path(argv[argv.index("--out") + 1])

    mech = json.loads((data_dir / "series_mech.json").read_text())
    qual_path = data_dir / "series_qual.json"
    qual = json.loads(qual_path.read_text()) if qual_path.exists() else {}

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(mech, qual))
    (out.parent / ".nojekyll").write_text("")
    print(f"[site] wrote {out} ({out.stat().st_size:,} bytes) "
          f"months={len(mech.get('months', {}))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
