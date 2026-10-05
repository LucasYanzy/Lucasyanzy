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
        return {"tokens": "14.36B", "cost": "$7,513", "rank": "#519", "tokens_month": "886.93M", "cost_month": "$412"}
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


def render(data, now):
    W, H, PAD = 880, 288, 36
    o, a = [], None
    a = o.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">')
    summary = f'{NAME}: {data["tokens"]} tokens, {data["cost"]} cost, rank {data["rank"]} on TokenTracker'
    a(f'<title id="t">AI Coding Usage</title><desc id="d">{html.escape(summary)}</desc>')
    a(f'''<defs>
  <clipPath id="clip"><rect width="{W}" height="{H}" rx="20"/></clipPath>
  <filter id="soft" filterUnits="userSpaceOnUse" x="-300" y="-300" width="1480" height="900"><feGaussianBlur stdDeviation="60"/></filter>
  <filter id="glow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="3"/></filter>
  <linearGradient id="av" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{CYAN}"/><stop offset="1" stop-color="{PURPLE}"/></linearGradient>
  <linearGradient id="ring" x1="0" x2="1"><stop offset="0" stop-color="{CYAN}"/><stop offset="1" stop-color="{PURPLE}"/></linearGradient>
  <linearGradient id="orbit" x1="0" x2="1"><stop offset="0" stop-color="{CYAN}" stop-opacity="0"/><stop offset=".3" stop-color="{CYAN}" stop-opacity=".8"/><stop offset=".7" stop-color="{PURPLE}" stop-opacity=".8"/><stop offset="1" stop-color="{PURPLE}" stop-opacity="0"/></linearGradient>
  <linearGradient id="edge" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{CYAN}" stop-opacity=".5"/><stop offset=".5" stop-color="#fff" stop-opacity=".08"/><stop offset="1" stop-color="{PURPLE}" stop-opacity=".5"/></linearGradient>
  <linearGradient id="sheen" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".10"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
</defs>''')
    a('<g clip-path="url(#clip)">')
    a(f'<rect width="{W}" height="{H}" fill="#04060a"/>')
    a('<g filter="url(#soft)">'
      f'<ellipse cx="170" cy="30" rx="300" ry="90" fill="{CYAN}" fill-opacity=".24"/>'
      '<ellipse cx="470" cy="170" rx="300" ry="80" fill="#046ebe" fill-opacity=".28"/>'
      f'<ellipse cx="760" cy="290" rx="320" ry="90" fill="{PURPLE}" fill-opacity=".26"/></g>')

    # orbit rings + planets
    cx, cy = W / 2, H / 2
    a(f'<g transform="rotate(-6 {cx} {cy})" fill="none">')
    for rx, ry, op in [(300, 64, .55), (440, 104, .38), (600, 150, .24)]:
        a(f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" stroke="url(#orbit)" stroke-width="1.2" stroke-opacity="{op}"/>')
    for rx, ry, r, col, dur, off, rev in [(300, 64, 3, CYAN, 26, 6, 0), (440, 104, 3.6, PURPLE, 36, 20, 1), (600, 150, 3, CYAN, 48, 30, 0)]:
        sw = 0 if rev else 1
        path = f"M{cx+rx} {cy} A{rx} {ry} 0 1 {sw} {cx-rx} {cy} A{rx} {ry} 0 1 {sw} {cx+rx} {cy}"
        for rad, flt, op in [(r * 2.8, ' filter="url(#glow)"', .75), (r, '', 1)]:
            a(f'<circle r="{rad:.1f}" fill="{col}" fill-opacity="{op}"{flt}><animateMotion dur="{dur}s" begin="-{off}s" repeatCount="indefinite" path="{path}"/></circle>')
    a('</g>')
    random.seed(33)
    for _ in range(26):
        x, y = random.uniform(14, W - 14), random.uniform(10, H - 10)
        a(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{random.choice([.8, 1, 1.3, 1.6])}" fill="#fff" fill-opacity="{random.uniform(.2, .5):.2f}"/>')

    # header: avatar, title, status
    ax, ay = PAD + 40, 72
    a(f'<circle cx="{ax}" cy="{ay}" r="46" fill="none" stroke="url(#ring)" stroke-width="1.6" stroke-dasharray="3 7" stroke-linecap="round" opacity=".85">'
      f'<animateTransform attributeName="transform" type="rotate" from="0 {ax} {ay}" to="360 {ax} {ay}" dur="14s" repeatCount="indefinite"/></circle>')
    a(f'<circle cx="{ax}" cy="{ay}" r="34" fill="url(#av)"/>')
    a(f'<text x="{ax}" y="{ay+12}" text-anchor="middle" font-family="{SANS}" font-size="34" font-weight="700" fill="#04060a">{html.escape(NAME[:1].upper())}</text>')
    a(f'<text x="{PAD+100}" y="66" font-family="{SANS}" font-size="30" font-weight="700" fill="#fff">{html.escape(NAME)}</text>')
    a(f'<text x="{PAD+100}" y="92" font-family="{SANS}" font-size="15" fill="#fff" fill-opacity=".55">AI Coding Usage · All time</text>')
    right = W - PAD
    a(f'<text x="{right}" y="62" text-anchor="end" font-family="{SANS}" font-size="16" font-weight="600" fill="{CYAN}">TokenTracker</text>')
    stamp = f"Updated {now.day} {now.strftime('%b')} {now.year}"
    a(f'<text x="{right}" y="88" text-anchor="end" font-family="{SANS}" font-size="13" fill="#fff" fill-opacity=".55">{stamp}</text>')
    dx = right - len(stamp) * 6.7 - 20
    a(f'<circle cx="{dx:.1f}" cy="83.5" r="3.4" fill="#34d399"/>'
      f'<circle cx="{dx:.1f}" cy="83.5" r="3.4" fill="none" stroke="#34d399" stroke-width="1.4"><animate attributeName="r" values="3.4;10;3.4" dur="2.6s" repeatCount="indefinite"/>'
      '<animate attributeName="stroke-opacity" values=".9;0;.9" dur="2.6s" repeatCount="indefinite"/></circle>')

    # stat tiles
    tw, gap, ty, th = 250, 25, 128, 128
    tiles = [
        ("Tokens", data["tokens"], "#ffffff", f'{data["tokens_month"]} this month' if "tokens_month" in data else ""),
        ("Cost", data["cost"], "#ffffff", f'{data["cost_month"]} this month' if "cost_month" in data else ""),
        ("Rank", data["rank"], CYAN, "TokenTracker leaderboard"),
    ]
    all_defs = []
    for i, (label, value, color, sub) in enumerate(tiles):
        tx = PAD + i * (tw + gap)
        a(f'<rect x="{tx+.5}" y="{ty+.5}" width="{tw-1}" height="{th-1}" rx="16" fill="#070b12" fill-opacity=".78" stroke="{CYAN}" stroke-opacity=".2"/>')
        a(f'<rect x="{tx+.5}" y="{ty+.5}" width="{tw-1}" height="{th-1}" rx="16" fill="#fff" fill-opacity=".03"/>')
        a(f'<text x="{tx+26}" y="{ty+34}" font-family="{SANS}" font-size="14" fill="#fff" fill-opacity=".6">{label}</text>')
        defs, g = rolling(value, tx + 26, ty + 88, 46, color, f"r{i}_")
        all_defs.append(defs)
        a(g)
        if sub:
            a(f'<text x="{tx+26}" y="{ty+114}" font-family="{SANS}" font-size="12.5" fill="#fff" fill-opacity=".5">{html.escape(sub)}</text>')
    # sheen sweep across the tiles
    a(f'<clipPath id="tiles"><rect x="{PAD}" y="{ty}" width="{W-2*PAD}" height="{th}" rx="16"/></clipPath>')
    a(f'<g clip-path="url(#tiles)"><rect x="-240" y="{ty}" width="200" height="{th}" fill="url(#sheen)" transform="skewX(-18)">'
      f'<animate attributeName="x" values="-240;{W+40};{W+40}" keyTimes="0;.28;1" dur="9s" repeatCount="indefinite"/></rect></g>')

    a(f'<rect x=".75" y=".75" width="{W-1.5}" height="{H-1.5}" rx="19.5" fill="none" stroke="url(#edge)" stroke-width="1.5"/>')
    a('</g></svg>')
    svg = "\n".join(o)
    # clipPaths for the rolling digits must live in <defs>; hoist them
    svg = svg.replace("</defs>", "".join(all_defs) + "</defs>", 1)
    return svg


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
