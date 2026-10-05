#!/usr/bin/env python3
"""Render the "AI Coding Usage" card from TokenTracker's public badge endpoint.

Standard library only. Reads tokens / cost / rank (all time) plus this month's
tokens and cost for one public TokenTracker profile and writes dist/ai-usage.svg
(an animated card in the portfolio's cyan/purple palette) and dist/ai-usage.json.

Set AI_USAGE_SAMPLE=1 to render with fixed sample numbers (no network).
"""
import datetime
import html
import json
import math
import os
import random
import re
import sys
import urllib.parse
import urllib.request

USER_ID = os.environ.get("TOKENTRACKER_USER_ID", "28d52253-68ed-4de0-978b-8e70fe5eb800")
BASE = "https://srctyff5.us-east.insforge.app/functions/tokentracker-badge-svg"
NAME = os.environ.get("CARD_NAME", "Lucas Yan")
OUT_DIR = os.environ.get("OUT_DIR", "dist")

CYAN, PURPLE = "#00f3ff", "#bd00ff"
SANS = "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"


# ------------------------------------------------------------------ data
def fetch_badge(metric, period="total"):
    qs = urllib.parse.urlencode({"user_id": USER_ID, "metric": metric, "period": period})
    req = urllib.request.Request(f"{BASE}?{qs}", headers={"User-Agent": "profile-readme-card/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def parse_badge(svg):
    """shields-style badge: aria-label="<label>: <value>" -> value (without a trailing ' tokens')."""
    m = re.search(r'aria-label="([^"]*)"', svg)
    if not m or ": " not in m.group(1):
        raise ValueError(f"unexpected badge: {svg[:160]!r}")
    value = html.unescape(m.group(1).split(": ", 1)[1]).strip()
    value = re.sub(r"\s+tokens$", "", value, flags=re.I)
    if not value:
        raise ValueError("empty badge value (is the TokenTracker profile public?)")
    return value


def collect():
    if os.environ.get("AI_USAGE_SAMPLE"):
        return {"tokens": "14.36B", "cost": "$7,513", "rank": "#519", "tokens_month": "886.93M", "cost_month": "$336",
                "providers": [{"name": "Claude", "pct": 82}, {"name": "Codex", "pct": 13}, {"name": "Other", "pct": 5}]}
    data = {}
    for key, metric, period, required in [
        ("tokens", "tokens", "total", True), ("cost", "cost", "total", True), ("rank", "rank", "total", True),
        ("tokens_month", "tokens", "month", False), ("cost_month", "cost", "month", False),
    ]:
        try:
            data[key] = parse_badge(fetch_badge(metric, period))
        except Exception as e:  # noqa: BLE001
            if required:
                raise
            print(f"::warning::optional metric {key} unavailable: {e}")
    return data


# ------------------------------------------------------------------ drawing
ADV = {".": .30, ",": .30, "$": .62, "#": .64, "B": .70, "M": .86, "K": .68, "T": .62, "k": .56, "m": .86, "b": .60}
DIGIT = .62
CYCLE = 16.0   # seconds per replay of the roll
ROLL = 1.9     # seconds for the digits to settle


def rolling(value, x0, y0, fs, fill, uid):
    """Left-aligned number whose digits roll like a slot machine; other glyphs stay put.
    Base (non-animated) state is the final value, so renderers without SMIL still show it correctly."""
    lh = fs * 1.18
    defs, body, x, n = [], [], x0, 0
    for ch in value:
        adv = (DIGIT if ch.isdigit() else ADV.get(ch, .62)) * fs
        cx = x + adv / 2
        if ch.isdigit():
            d = int(ch)
            cid = f"{uid}{n}"
            defs.append(f'<clipPath id="{cid}"><rect x="{x-1:.1f}" y="{y0-fs*.84:.1f}" width="{adv+2:.1f}" height="{fs*1.02:.1f}"/></clipPath>')
            col = "".join(f'<text x="{cx:.1f}" y="{y0+i*lh:.1f}">{i}</text>' for i in range(10))
            ty = d * lh
            s = n * 0.16 / CYCLE
            r = ROLL / CYCLE
            anim = (f'<animateTransform attributeName="transform" type="translate" dur="{CYCLE}s" repeatCount="indefinite" '
                    f'calcMode="spline" keyTimes="0;{s:.4f};{s+r:.4f};1" keySplines="0 0 1 1;.16 .84 .3 1;0 0 1 1" '
                    f'values="0 0;0 0;0 {-ty:.1f};0 {-ty:.1f}"/>') if d else ''
            body.append(f'<g clip-path="url(#{cid})"><g transform="translate(0 {-ty:.1f})">{col}{anim}</g></g>')
            n += 1
        else:
            body.append(f'<text x="{cx:.1f}" y="{y0:.1f}">{html.escape(ch)}</text>')
        x += adv
    g = (f'<g font-family="{SANS}" font-weight="700" font-size="{fs}" text-anchor="middle" fill="{fill}" '
         f'style="font-variant-numeric:tabular-nums">{"".join(body)}</g>')
    return "".join(defs), g


def provider_pct(p):
    v = p["pct"]
    return "<1%" if v < 1 else f"{round(v):d}%"


def render(data, now):
    """Calm, premium dashboard card: hairlines instead of boxes, large numerals, one provider bar."""
    W, PAD = 880, 40
    prov = data.get("providers") or []
    H = 346 if prov else 252
    o = []
    a = o.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">')
    summary = f'{NAME}: {data["tokens"]} tokens, {data["cost"]} cost, rank {data["rank"]} on TokenTracker'
    if prov:
        summary += ". Top providers: " + ", ".join(f'{p["name"]} {provider_pct(p)}' for p in prov)
    a(f'<title id="t">AI Coding Usage</title><desc id="d">{html.escape(summary)}</desc>')
    bar_x, bar_w, bar_y, bar_h = PAD, W - 2 * PAD, 288, 10
    segs = ['#00f3ff;#38bdf8', '#bd00ff;#7c3aed', '#64748b;#475569', '#94a3b8;#64748b', '#334155;#1e293b']
    grads = "".join(
        f'<linearGradient id="seg{i}" x1="0" x2="1"><stop offset="0" stop-color="{c.split(";")[0]}"/><stop offset="1" stop-color="{c.split(";")[1]}"/></linearGradient>'
        for i, c in enumerate(segs))
    a(f"""<defs>
  <clipPath id="clip"><rect width="{W}" height="{H}" rx="22"/></clipPath>
  <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0d1424"/><stop offset="1" stop-color="#070a12"/></linearGradient>
  <radialGradient id="g1" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(90 -20) scale(520 260)"><stop offset="0" stop-color="{CYAN}" stop-opacity=".16"/><stop offset="1" stop-color="{CYAN}" stop-opacity="0"/></radialGradient>
  <radialGradient id="g2" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate({W} {H}) scale(460 240)"><stop offset="0" stop-color="{PURPLE}" stop-opacity=".13"/><stop offset="1" stop-color="{PURPLE}" stop-opacity="0"/></radialGradient>
  <linearGradient id="accent" x1="0" x2="1"><stop offset="0" stop-color="{CYAN}"/><stop offset="1" stop-color="{PURPLE}"/></linearGradient>
  <linearGradient id="hl" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".38"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <linearGradient id="sheen" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".55"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
  {grads}
  <clipPath id="barclip"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="{bar_h/2}">
    <animate attributeName="width" values="0;{bar_w};{bar_w}" keyTimes="0;.09;1" dur="{CYCLE}s" repeatCount="indefinite" calcMode="spline" keySplines=".16 .84 .3 1;0 0 1 1"/></rect></clipPath>
  <clipPath id="bartrack"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="{bar_h/2}"/></clipPath>
</defs>""")
    a('<g clip-path="url(#clip)">')
    a(f'<rect width="{W}" height="{H}" fill="url(#bg)"/>')
    a(f'<rect width="{W}" height="{H}" fill="url(#g1)"><animate attributeName="opacity" values=".75;1;.75" dur="9s" repeatCount="indefinite"/></rect>')
    a(f'<rect width="{W}" height="{H}" fill="url(#g2)"/>')
    a(f'<rect x="28" y="0" width="{W-56}" height="1" fill="url(#hl)"/>')

    # ---- header
    ax, ay = PAD + 30, 58
    a(f'<circle cx="{ax}" cy="{ay}" r="30" fill="none" stroke="url(#accent)" stroke-width="1.6"/>')
    a(f'<circle cx="{ax}" cy="{ay}" r="25" fill="#0f1a2e"/>')
    a(f'<text x="{ax}" y="{ay+9}" text-anchor="middle" font-family="{SANS}" font-size="25" font-weight="700" fill="url(#accent)">{html.escape(NAME[:1].upper())}</text>')
    a(f'<text x="{PAD+78}" y="54" font-family="{SANS}" font-size="26" font-weight="700" fill="#f8fafc">{html.escape(NAME)}</text>')
    a(f'<text x="{PAD+78}" y="78" font-family="{SANS}" font-size="14" fill="#94a3b8">AI coding usage · All time</text>')
    right = W - PAD
    a(f'<text x="{right}" y="50" text-anchor="end" font-family="{SANS}" font-size="15" font-weight="600" fill="#e2e8f0">TokenTracker</text>')
    stamp = f"Live · {now.day} {now.strftime('%b')} {now.year}"
    a(f'<text x="{right}" y="74" text-anchor="end" font-family="{SANS}" font-size="13" fill="#94a3b8">{stamp}</text>')
    dx = right - len(stamp) * 6.6 - 14
    a(f'<circle cx="{dx:.1f}" cy="70" r="3.2" fill="#34d399"/>'
      f'<circle cx="{dx:.1f}" cy="70" r="3.2" fill="none" stroke="#34d399" stroke-width="1.3"><animate attributeName="r" values="3.2;9;3.2" dur="2.8s" repeatCount="indefinite"/>'
      '<animate attributeName="stroke-opacity" values=".8;0;.8" dur="2.8s" repeatCount="indefinite"/></circle>')
    a(f'<rect x="{PAD}" y="104" width="{W-2*PAD}" height="1" fill="#fff" fill-opacity=".08"/>')

    # ---- metrics (hairline columns, no boxes)
    cw = (W - 2 * PAD) / 3
    cols = [
        ("Tokens", data["tokens"], "#f8fafc", f'{data["tokens_month"]} this month' if "tokens_month" in data else ""),
        ("Cost", data["cost"], "#f8fafc", f'{data["cost_month"]} this month' if "cost_month" in data else ""),
        ("Rank", data["rank"], CYAN, "on the TokenTracker leaderboard"),
    ]
    all_defs = []
    for i, (label, value, color, sub) in enumerate(cols):
        cx0 = PAD + i * cw + (0 if i == 0 else 30)
        if i:
            a(f'<rect x="{PAD + i*cw:.1f}" y="128" width="1" height="92" fill="#fff" fill-opacity=".08"/>')
        a(f'<text x="{cx0:.1f}" y="146" font-family="{SANS}" font-size="13.5" fill="#94a3b8">{label}</text>')
        defs, g = rolling(value, cx0, 200, 52, color, f"r{i}_")
        all_defs.append(defs)
        a(g)
        if sub:
            a(f'<text x="{cx0:.1f}" y="226" font-family="{SANS}" font-size="13" fill="#64748b">{html.escape(sub)}</text>')

    # ---- providers
    if prov:
        a(f'<rect x="{PAD}" y="248" width="{W-2*PAD}" height="1" fill="#fff" fill-opacity=".08"/>')
        a(f'<text x="{PAD}" y="276" font-family="{SANS}" font-size="13.5" fill="#94a3b8">Top providers</text>')
        a(f'<g clip-path="url(#bartrack)"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" fill="#fff" fill-opacity=".07"/></g>')
        a('<g clip-path="url(#barclip)">')
        x, gap = float(bar_x), 4.0
        for i, p in enumerate(prov):
            w = bar_w * p["pct"] / 100.0
            w = max(w, 8.0)
            a(f'<rect x="{x:.1f}" y="{bar_y}" width="{max(w - gap, 4):.1f}" height="{bar_h}" rx="{bar_h/2}" fill="url(#seg{min(i, len(segs)-1)})"/>')
            x += w
        a('</g>')
        a(f'<g clip-path="url(#bartrack)"><rect x="-120" y="{bar_y}" width="110" height="{bar_h}" fill="url(#sheen)" transform="skewX(-20)">'
          f'<animate attributeName="x" values="-120;{W+40};{W+40}" keyTimes="0;.22;1" dur="{CYCLE}s" begin="1.1s" repeatCount="indefinite"/></rect></g>')
        lx = float(PAD)
        for i, p in enumerate(prov):
            pct = provider_pct(p)
            a(f'<circle cx="{lx+5:.1f}" cy="321" r="4.5" fill="url(#seg{min(i, len(segs)-1)})"/>')
            a(f'<text x="{lx+16:.1f}" y="326" font-family="{SANS}" font-size="14" fill="#e2e8f0">{html.escape(p["name"])}'
              f'<tspan dx="8" fill="#94a3b8" style="font-variant-numeric:tabular-nums">{pct}</tspan></text>')
            lx += 16 + len(p["name"]) * 8.2 + len(pct) * 8.0 + 8 + 34

    a(f'<rect x=".5" y=".5" width="{W-1}" height="{H-1}" rx="21.5" fill="none" stroke="#fff" stroke-opacity=".09"/>')
    a('</g></svg>')
    svg = "\n".join(o)
    return svg.replace("</defs>", "".join(all_defs) + "</defs>", 1)


def main():
    data = collect()
    now = datetime.datetime.now(datetime.timezone.utc)
    os.makedirs(OUT_DIR, exist_ok=True)
    svg = render(data, now)
    with open(os.path.join(OUT_DIR, "ai-usage.svg"), "w", encoding="utf-8") as f:
        f.write(svg)
    with open(os.path.join(OUT_DIR, "ai-usage.json"), "w", encoding="utf-8") as f:
        json.dump({**data, "updated": now.isoformat(timespec="seconds")}, f, indent=2)
    print(f"ai-usage.svg written ({len(svg)} bytes): {data}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        # keep the last good card: report and stop without publishing
        print(f"::warning::AI usage card not updated: {e}")
        sys.exit(1)
