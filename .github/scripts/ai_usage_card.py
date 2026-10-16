#!/usr/bin/env python3
"""Render the "AI Coding Usage" card from TokenTracker's public badge endpoint.

Standard library only. Reads tokens / cost / rank (all time) plus this month's
tokens and cost for one public TokenTracker profile and writes dist/ai-usage.svg
(an animated dashboard card) and dist/ai-usage.json.

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
import xml.etree.ElementTree as ET

USER_ID = os.environ.get("TOKENTRACKER_USER_ID", "28d52253-68ed-4de0-978b-8e70fe5eb800")
BASE = "https://srctyff5.us-east.insforge.app/functions/tokentracker-badge-svg"
PROFILE = "https://srctyff5.us-east.insforge.app/functions/tokentracker-leaderboard-profile"
PROVIDER_NAMES = {"claude": "Claude", "codex": "Codex", "other": "Other", "gemini": "Gemini", "cursor": "Cursor",
                  "copilot": "Copilot", "opencode": "OpenCode", "kimi": "Kimi", "deepseek": "DeepSeek"}
MAX_PROVIDERS = 4
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


def fetch_providers():
    """All-time provider split from the public profile endpoint (period=total), largest first.
    `percent` is a fraction of total tokens. More than MAX_PROVIDERS rows fold into "Other"."""
    qs = urllib.parse.urlencode({"user_id": USER_ID, "period": "total"})
    req = urllib.request.Request(f"{PROFILE}?{qs}", headers={"User-Agent": "profile-readme-card/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        profile = json.load(r)
    if (profile.get("period") or {}).get("kind") != "total":
        raise ValueError("profile endpoint did not return the all-time period")
    rows = []
    for row in profile.get("by_provider") or []:
        src = str(row.get("source") or "other").lower()
        pct = float(row.get("percent") or 0) * 100.0
        if pct > 0:
            rows.append({"key": src, "name": PROVIDER_NAMES.get(src, src.replace("-", " ").title()), "pct": pct})
    rows.sort(key=lambda r: r["pct"], reverse=True)
    if len(rows) > MAX_PROVIDERS:
        keep, rest = rows[: MAX_PROVIDERS - 1], rows[MAX_PROVIDERS - 1:]
        other = sum(r["pct"] for r in rest)
        existing = next((r for r in keep if r["key"] == "other"), None)
        if existing:
            existing["pct"] += other
        else:
            keep.append({"key": "other", "name": "Other", "pct": other})
        rows = sorted(keep, key=lambda r: r["pct"], reverse=True)
    return rows


def collect():
    if os.environ.get("AI_USAGE_SAMPLE"):
        return {"tokens": "14.36B", "cost": "$7,513", "rank": "#519", "tokens_month": "886.93M", "cost_month": "$336",
                "providers": [{"key": "codex", "name": "Codex", "pct": 42.6}, {"key": "other", "name": "Other", "pct": 33.7},
                              {"key": "claude", "name": "Claude", "pct": 23.6}, {"key": "cursor", "name": "Cursor", "pct": 0.05}]}
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
    try:
        providers = fetch_providers()
        if providers:
            data["providers"] = providers
    except Exception as e:  # noqa: BLE001
        print(f"::warning::top providers unavailable, card drawn without them: {e}")
    return data


# ------------------------------------------------------------------ drawing
ADV = {".": .30, ",": .30, "$": .62, "#": .64, "B": .70, "M": .86, "K": .68, "T": .62, "k": .56, "m": .86, "b": .60}
DIGIT = .62
CYCLE = 16.0   # seconds per replay of the roll
ROLL = 1.9     # seconds for the digits to settle

# brand-ish colours per provider: (light end, dark end) of the bar gradient
PROVIDER_COLORS = {
    "claude": ("#f2a583", "#d97757"),
    "codex": ("#9aa8ff", "#5f6fff"),
    "cursor": ("#e2e8f0", "#94a3b8"),
    "gemini": ("#7db0ff", "#a78bfa"),
    "other": ("#94a3b8", "#64748b"),
}
FALLBACK_COLORS = [("#5eead4", "#2dd4bf"), ("#fcd34d", "#f59e0b"), ("#f9a8d4", "#ec4899"), ("#bef264", "#84cc16")]


def text_width(value, fs):
    return sum((DIGIT if ch.isdigit() else ADV.get(ch, .62)) * fs for ch in value)


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
    g = (f'<g font-family="{SANS}" font-weight="700" font-size="{fs:.1f}" text-anchor="middle" fill="{fill}" '
         f'style="font-variant-numeric:tabular-nums">{"".join(body)}</g>')
    return "".join(defs), g


def provider_pct(p):
    v = p["pct"]
    if v < 0.1:
        return "<0.1%"
    return f"{v:.1f}".rstrip("0").rstrip(".") + "%"


def provider_icon(key, cx, cy, uid):
    """A small 22px mark for a provider, drawn from plain shapes (no external images)."""
    x, y = cx - 11, cy - 11
    if key == "claude":
        rays = []
        for k in range(12):
            ang = math.radians(k * 30 - 90)
            r0, r1 = 2.4, (10.0 if k % 2 == 0 else 7.4)
            rays.append(f'<line x1="{cx + r0*math.cos(ang):.2f}" y1="{cy + r0*math.sin(ang):.2f}" '
                        f'x2="{cx + r1*math.cos(ang):.2f}" y2="{cy + r1*math.sin(ang):.2f}"/>')
        return "", f'<g stroke="#e08b69" stroke-width="2.1" stroke-linecap="round">{"".join(rays)}</g>'
    if key == "codex":
        gid = f"{uid}ic"
        defs = f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#9aa8ff"/><stop offset="1" stop-color="#5566f5"/></linearGradient>'
        body = (f'<rect x="{x}" y="{y}" width="22" height="22" rx="7" fill="url(#{gid})"/>'
                f'<path d="M{cx-5.2:.1f} {cy-4.2:.1f} L{cx-0.8:.1f} {cy-0.2:.1f} L{cx-5.2:.1f} {cy+3.8:.1f}" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
                f'<line x1="{cx+1.6:.1f}" y1="{cy+4.4:.1f}" x2="{cx+6:.1f}" y2="{cy+4.4:.1f}" stroke="#fff" stroke-width="2" stroke-linecap="round"/>')
        return defs, body
    if key == "cursor":
        gid = f"{uid}ic"
        defs = f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4b5266"/><stop offset="1" stop-color="#242833"/></linearGradient>'
        pts = [(-4, -6), (-4, 5), (-1, 2.2), (1.4, 7), (3.6, 6), (1.2, 1.4), (5, 1.4)]
        poly = " ".join(f"{cx+px:.1f},{cy+py:.1f}" for px, py in pts)
        return defs, (f'<rect x="{x}" y="{y}" width="22" height="22" rx="7" fill="url(#{gid})" stroke="#fff" stroke-opacity=".14"/>'
                      f'<polygon points="{poly}" fill="#fff"/>')
    if key == "gemini":
        gid = f"{uid}ic"
        defs = f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5b9bff"/><stop offset="1" stop-color="#b48cff"/></linearGradient>'
        d = (f"M{cx} {cy-10.5} C{cx} {cy-3.5} {cx+3.5} {cy} {cx+10.5} {cy} C{cx+3.5} {cy} {cx} {cy+3.5} {cx} {cy+10.5} "
             f"C{cx} {cy+3.5} {cx-3.5} {cy} {cx-10.5} {cy} C{cx-3.5} {cy} {cx} {cy-3.5} {cx} {cy-10.5} Z")
        return defs, f'<path d="{d}" fill="url(#{gid})"/>'
    # other / unknown: a quiet tile with three dots
    dots = "".join(f'<circle cx="{cx+dx}" cy="{cy}" r="1.7" fill="#cbd5e1"/>' for dx in (-5.2, 0, 5.2))
    return "", (f'<rect x="{x}" y="{y}" width="22" height="22" rx="7" fill="#fff" fill-opacity=".06" stroke="#fff" stroke-opacity=".14"/>{dots}')


def render(data, now):
    """Dashboard card: name and brand on top; tokens / cost / rank as large numerals; top providers with
    an icon, a thin bar and the share. Everything dynamic is escaped and the result is XML-checked in main()."""
    W, PAD = 1060, 44
    prov = data.get("providers") or []
    H = 300 + (30 if len(prov) > 3 else 0)
    LABEL_Y = 180
    VALUE_Y = LABEL_Y + (72 if len(prov) > 3 else 66)
    SOFT, MUTED = "#8b93a7", "#7b8499"
    summary = f'{NAME}: {data["tokens"]} tokens, {data["cost"]} cost, rank {data["rank"]} on TokenTracker'
    if prov:
        summary += ". Top providers: " + ", ".join(f'{p["name"]} {provider_pct(p)}' for p in prov)

    # --- layout: provider panel on the right, metrics share what is left
    panel_w = 252
    panel_x = W - PAD - panel_w if prov else W
    avail = (panel_x - 34 - 30 if prov else W - PAD) - PAD   # keep a margin before the divider
    values = [data["tokens"], data["cost"], data["rank"]]
    gap = 68
    fs = 54.0
    need = sum(text_width(v, fs) for v in values) + 2 * gap
    if need > avail:
        fs = max(36.0, fs * avail / need)
    widths = [max(text_width(v, fs), 90) for v in values]
    xs = [float(PAD)]
    for w in widths[:-1]:
        xs.append(xs[-1] + w + gap)

    o, a = [], None
    a = o.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">')
    a(f'<title id="t">AI Coding Usage</title><desc id="d">{html.escape(summary)}</desc>')

    defs = [f"""
  <clipPath id="clip"><rect width="{W}" height="{H}" rx="26"/></clipPath>
  <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0c1020"/><stop offset="1" stop-color="#07090f"/></linearGradient>
  <radialGradient id="glowA" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate({W*0.74:.0f} -30) scale(560 300)"><stop offset="0" stop-color="#7c6cff" stop-opacity=".30"/><stop offset=".55" stop-color="#4f46e5" stop-opacity=".08"/><stop offset="1" stop-color="#4f46e5" stop-opacity="0"/></radialGradient>
  <radialGradient id="glowB" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(40 {H+20}) scale(460 220)"><stop offset="0" stop-color="{CYAN}" stop-opacity=".10"/><stop offset="1" stop-color="{CYAN}" stop-opacity="0"/></radialGradient>
  <linearGradient id="edge" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".18"/><stop offset=".5" stop-color="#fff" stop-opacity=".06"/><stop offset="1" stop-color="#fff" stop-opacity=".10"/></linearGradient>
  <linearGradient id="hl" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".5"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <linearGradient id="rankGrad" gradientUnits="userSpaceOnUse" x1="{xs[2]:.1f}" y1="0" x2="{xs[2]+widths[2]:.1f}" y2="0"><stop offset="0" stop-color="#67e8f9"/><stop offset="1" stop-color="#a78bfa"/></linearGradient>
  <linearGradient id="brandGrad" gradientUnits="userSpaceOnUse" x1="{W-PAD-210}" y1="0" x2="{W-PAD-58}" y2="0"><stop offset="0" stop-color="#67e8f9"/><stop offset="1" stop-color="#a78bfa"/></linearGradient>
  <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2d3346"/><stop offset="1" stop-color="#10131c"/></linearGradient>"""]

    body = []
    b = body.append
    b('<g clip-path="url(#clip)">')
    b(f'<rect width="{W}" height="{H}" fill="url(#bg)"/>')
    b(f'<rect width="{W}" height="{H}" fill="url(#glowA)"><animate attributeName="opacity" values=".8;1;.8" dur="10s" repeatCount="indefinite"/></rect>')
    b(f'<rect width="{W}" height="{H}" fill="url(#glowB)"/>')
    b(f'<rect x="34" y="0" width="{W-68}" height="1" fill="url(#hl)"/>')

    # --- header: name + status on the left, brand on the right
    b(f'<text x="{PAD}" y="84" font-family="{SANS}" font-size="34" font-weight="700" letter-spacing="-.4" fill="#f8fafc">{html.escape(NAME)}</text>')
    b('<circle cx="{0}" cy="107" r="3.4" fill="#34d399"/>'.format(PAD + 4))
    b(f'<circle cx="{PAD+4}" cy="107" r="3.4" fill="none" stroke="#34d399" stroke-width="1.3"><animate attributeName="r" values="3.4;9;3.4" dur="2.8s" repeatCount="indefinite"/>'
      '<animate attributeName="stroke-opacity" values=".8;0;.8" dur="2.8s" repeatCount="indefinite"/></circle>')
    stamp = f"Total usage · updated {now.day} {now.strftime('%b')} {now.year}"
    b(f'<text x="{PAD+18}" y="112" font-family="{SANS}" font-size="15.5" fill="{SOFT}">{html.escape(stamp)}</text>')

    tile = 46
    tx, ty = W - PAD - tile, 40
    b(f'<rect x="{tx}" y="{ty}" width="{tile}" height="{tile}" rx="13" fill="url(#tile)" stroke="#fff" stroke-opacity=".16"/>')
    bolt = f"M{tx+26} {ty+9} L{tx+12.5} {ty+26.5} H{tx+22} L{tx+19.5} {ty+37.5} L{tx+33.5} {ty+19.5} H{tx+24} Z"
    b(f'<path d="{bolt}" fill="#fff"/>')
    brand_r = tx - 16
    b(f'<text x="{brand_r}" y="62" text-anchor="end" font-family="{SANS}" font-size="13.5" font-weight="700" letter-spacing="3.4" fill="url(#brandGrad)">TOKENTRACKER</text>')
    b(f'<text x="{brand_r}" y="83" text-anchor="end" font-family="{SANS}" font-size="13.5" fill="{MUTED}">tokentracker.cc</text>')

    # --- metrics
    labels = ["TOKENS", "COST", "RANK"]
    fills = ["#f8fafc", "#f8fafc", "url(#rankGrad)"]
    all_defs = []
    for i in range(3):
        if i:
            b(f'<rect x="{xs[i]-gap/2:.1f}" y="{LABEL_Y-26}" width="1" height="{VALUE_Y-LABEL_Y+44}" fill="#fff" fill-opacity=".08"/>')
        b(f'<text x="{xs[i]:.1f}" y="{LABEL_Y}" font-family="{SANS}" font-size="13.5" font-weight="600" letter-spacing="3.2" fill="{SOFT}">{labels[i]}</text>')
        d, g = rolling(values[i], xs[i], VALUE_Y, fs, fills[i], f"r{i}_")
        all_defs.append(d)
        b(g)

    # --- top providers
    if prov:
        b(f'<rect x="{panel_x-34}" y="{LABEL_Y-26}" width="1" height="{H-(LABEL_Y-26)-34}" fill="#fff" fill-opacity=".08"/>')
        b(f'<text x="{panel_x}" y="{LABEL_Y}" font-family="{SANS}" font-size="13.5" font-weight="600" letter-spacing="3.2" fill="{SOFT}">TOP PROVIDERS</text>')
        bar_x = panel_x + 22 + 12 + 84
        pct_x = panel_x + panel_w
        bar_w = pct_x - 58 - bar_x
        fallback = iter(FALLBACK_COLORS * 2)
        for i, p in enumerate(prov):
            key = str(p.get("key") or "other")
            lo, hi = PROVIDER_COLORS.get(key) or next(fallback)
            cy = LABEL_Y + 30 + i * 28
            gid = f"pg{i}"
            defs.append(f'<linearGradient id="{gid}" x1="0" x2="1"><stop offset="0" stop-color="{lo}"/><stop offset="1" stop-color="{hi}"/></linearGradient>')
            idefs, icon = provider_icon(key, panel_x + 11, cy, f"pi{i}")
            if idefs:
                defs.append(idefs)
            b(icon)
            b(f'<text x="{panel_x+34}" y="{cy+5.5}" font-family="{SANS}" font-size="16" fill="#e6eaf2">{html.escape(p["name"])}</text>')
            fill_w = max(bar_w * p["pct"] / 100.0, 3.0)
            b(f'<rect x="{bar_x}" y="{cy-3}" width="{bar_w:.1f}" height="6" rx="3" fill="#fff" fill-opacity=".08"/>')
            b(f'<rect x="{bar_x}" y="{cy-3}" width="{fill_w:.1f}" height="6" rx="3" fill="url(#{gid})">'
              f'<animate attributeName="width" values="0;{fill_w:.1f};{fill_w:.1f}" keyTimes="0;.1;1" dur="{CYCLE}s" begin="{0.25 + i*0.14:.2f}s" '
              f'repeatCount="indefinite" calcMode="spline" keySplines=".16 .84 .3 1;0 0 1 1"/></rect>')
            b(f'<text x="{pct_x}" y="{cy+5.5}" text-anchor="end" font-family="{SANS}" font-size="15.5" fill="#c3cad9" '
              f'style="font-variant-numeric:tabular-nums">{html.escape(provider_pct(p))}</text>')

    b(f'<rect x=".5" y=".5" width="{W-1}" height="{H-1}" rx="25.5" fill="none" stroke="url(#edge)"/>')
    b('</g></svg>')

    a("<defs>" + "".join(defs) + "".join(all_defs) + "</defs>")
    o.extend(body)
    return "\n".join(o)


def validate_svg(svg):
    """The card is XML: one stray '<' or '&' makes browsers drop the whole image, so check before publishing."""
    ET.fromstring(svg)


def main():
    data = collect()
    now = datetime.datetime.now(datetime.timezone.utc)
    os.makedirs(OUT_DIR, exist_ok=True)
    svg = render(data, now)
    validate_svg(svg)  # never publish a card the browser could not parse
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
