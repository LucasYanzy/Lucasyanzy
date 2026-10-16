#!/usr/bin/env python3
"""Render the "AI Coding Usage" card from TokenTracker's public badge endpoint.

Standard library only. Reads tokens / cost / rank (all time) plus this month's
tokens and cost for one public TokenTracker profile and writes dist/ai-usage.svg
(an animated dashboard card) and dist/ai-usage.json.

Set AI_USAGE_SAMPLE=1 to render with fixed sample numbers (no network).
"""
import datetime
import html
import base64
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
MIN_SHARE = 1.0   # providers below this share (in %) are left off the card
NAME = os.environ.get("CARD_NAME", "Lucas Yan")
AVATAR_LOGIN = os.environ.get("CARD_AVATAR_LOGIN") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "LucasYanzy"
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
    rows = [r for r in rows if r["pct"] >= MIN_SHARE]
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


def fetch_avatar():
    """The GitHub avatar as a small data URI, or None (the card then draws a monogram)."""
    path = os.environ.get("CARD_AVATAR_FILE")
    try:
        if path:
            raw = open(path, "rb").read()
            ctype = "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png"
        elif os.environ.get("AI_USAGE_SAMPLE"):
            return None
        else:
            req = urllib.request.Request(f"https://github.com/{AVATAR_LOGIN}.png?size=96",
                                         headers={"User-Agent": "profile-readme-card/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                raw, ctype = r.read(), r.headers.get_content_type()
        if ctype not in ("image/png", "image/jpeg") or not raw or len(raw) > 60000:
            return None
        return f"data:{ctype};base64," + base64.b64encode(raw).decode("ascii")
    except Exception as e:  # noqa: BLE001
        print(f"::warning::avatar unavailable, using a monogram: {e}")
        return None


def collect():
    if os.environ.get("AI_USAGE_SAMPLE"):
        return {"tokens": "14.36B", "cost": "$7,513", "rank": "#519", "tokens_month": "886.93M", "cost_month": "$336",
                "providers": [{"key": "codex", "name": "Codex", "pct": 42.6}, {"key": "other", "name": "Other", "pct": 33.7},
                              {"key": "claude", "name": "Claude", "pct": 23.6}]}
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
DIM = "#7d879c"   # prefix and unit glyphs ($ # B M K) sit back so the digits carry the number

# (light end, dark end) of each provider's bar gradient
PROVIDER_COLORS = {
    "claude": ("#e8987a", "#d97757"),
    "codex": ("#b1a7ff", "#4a55ff"),
    "cursor": ("#e2e8f0", "#94a3b8"),
    "gemini": ("#66a6ff", "#3186ff"),
    "deepseek": ("#7f9bff", "#4d6bfe"),
    "kimi": ("#52a8ff", "#1783ff"),
    "copilot": ("#5bc8f8", "#a78bfa"),
    "other": ("#a3adc2", "#6b7690"),
}
FALLBACK_COLORS = [("#5eead4", "#2dd4bf"), ("#fcd34d", "#f59e0b"), ("#f9a8d4", "#ec4899"), ("#bef264", "#84cc16")]


def text_width(value, fs):
    return sum((DIGIT if ch.isdigit() else ADV.get(ch, .62)) * fs for ch in value)


def rolling(value, x0, y0, fs, fill, uid, dim_fill=DIM):
    """Left-aligned number whose digits roll like a slot machine; other glyphs stay put.
    Prefix/unit glyphs are dimmed. The base (non-animated) state is the final value, so renderers
    without SMIL still show it correctly."""
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
        elif ch in ".,":
            body.append(f'<text x="{cx:.1f}" y="{y0:.1f}">{html.escape(ch)}</text>')
        else:
            body.append(f'<text x="{cx:.1f}" y="{y0:.1f}" fill="{dim_fill}">{html.escape(ch)}</text>')
        x += adv
    g = (f'<g font-family="{SANS}" font-weight="700" font-size="{fs:.1f}" text-anchor="middle" fill="{fill}" '
         f'letter-spacing="-1" style="font-variant-numeric:tabular-nums">{"".join(body)}</g>')
    return "".join(defs), g


def provider_pct(p):
    v = p["pct"]
    if v < 0.1:
        return "<0.1%"
    return f"{v:.1f}".rstrip("0").rstrip(".") + "%"


ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "assets", "provider-icons")
ICON_SIZE = 24


def provider_icon(key, cx, cy, uid):
    """The provider's official mark from assets/provider-icons (a 24x24 SVG), placed as a nested <svg>.
    Ids inside the file are prefixed so several marks never collide; unknown providers get a quiet tile."""
    x, y = cx - ICON_SIZE / 2, cy - ICON_SIZE / 2
    path = os.path.join(ICON_DIR, f"{key}.svg")
    if re.fullmatch(r"[a-z0-9_-]+", key) and os.path.isfile(path):
        raw = open(path, encoding="utf-8").read()
        m = re.search(r'<svg\b([^>]*)>(.*)</svg>', raw, re.S)
        if m:
            attrs, inner = m.group(1), re.sub(r"<title>.*?</title>", "", m.group(2), flags=re.S)
            for old in re.findall(r'\bid="([^"]+)"', inner):
                new = f"{uid}-{old}"
                inner = inner.replace(f'id="{old}"', f'id="{new}"').replace(f"url(#{old})", f"url(#{new})").replace(f'href="#{old}"', f'href="#{new}"')
            extra = ""
            for name in ("fill", "fill-rule", "clip-rule"):
                am = re.search(rf'\b{name}="([^"]+)"', attrs)
                if am:
                    extra += f' {name}="{"#e8ecf4" if am.group(1) == "currentColor" else am.group(1)}"'
            inner = inner.replace("currentColor", "#e8ecf4")
            return "", (f'<svg x="{x:.1f}" y="{y:.1f}" width="{ICON_SIZE}" height="{ICON_SIZE}" viewBox="0 0 24 24"{extra}>{inner}</svg>')
    dots = "".join(f'<circle cx="{cx+dx}" cy="{cy}" r="1.7" fill="#cbd5e1"/>' for dx in (-5.2, 0, 5.2))
    return "", (f'<rect x="{x}" y="{y}" width="{ICON_SIZE}" height="{ICON_SIZE}" rx="7.5" fill="#fff" fill-opacity=".06" stroke="#fff" stroke-opacity=".14"/>{dots}')


def render(data, now, avatar=None):
    """Dashboard card: avatar, name and brand on top; tokens / cost / rank as large numerals with the
    month's gain underneath; top providers with an icon, a bar and the share. All dynamic text is escaped
    and main() parses the result as XML before anything is published."""
    W, PAD = 1100, 48
    prov = data.get("providers") or []
    H = 310 + (36 if len(prov) > 3 else 0)
    LABEL_Y = 172
    VALUE_Y = LABEL_Y + 64
    SUB_Y = VALUE_Y + 32
    SOFT, MUTED = "#8b93a7", "#7b8499"
    summary = f'{NAME}: {data["tokens"]} tokens, {data["cost"]} cost, rank {data["rank"]} on TokenTracker'
    if prov:
        summary += ". Top providers: " + ", ".join(f'{p["name"]} {provider_pct(p)}' for p in prov)

    # --- layout: provider panel on the right, metrics share what is left
    panel_w = 300
    panel_x = W - PAD - panel_w if prov else W
    avail = (panel_x - 34 - 30 if prov else W - PAD) - PAD   # keep a margin before the divider
    values = [data["tokens"], data["cost"], data["rank"]]
    gap = 60
    fs = 52.0
    need = sum(text_width(v, fs) for v in values) + 2 * gap
    if need > avail:
        fs = max(34.0, fs * avail / need)
    widths = [max(text_width(v, fs), 96) for v in values]
    xs = [float(PAD)]
    for w in widths[:-1]:
        xs.append(xs[-1] + w + gap)

    defs = []
    body = []
    b = body.append
    tile = 46
    tx, ty = W - PAD - tile, 38

    defs.append(f"""
  <clipPath id="clip"><rect width="{W}" height="{H}" rx="28"/></clipPath>
  <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0b0e1b"/><stop offset="1" stop-color="#06070c"/></linearGradient>
  <radialGradient id="glowA" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate({W*0.72:.0f} -40) scale(620 330)"><stop offset="0" stop-color="#7c6cff" stop-opacity=".34"/><stop offset=".5" stop-color="#5b4df0" stop-opacity=".10"/><stop offset="1" stop-color="#4f46e5" stop-opacity="0"/></radialGradient>
  <radialGradient id="glowB" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(30 {H+30}) scale(520 240)"><stop offset="0" stop-color="#22d3ee" stop-opacity=".13"/><stop offset="1" stop-color="#22d3ee" stop-opacity="0"/></radialGradient>
  <radialGradient id="dotFade" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate({W*0.78:.0f} 10) scale(520 260)"><stop offset="0" stop-color="#fff" stop-opacity="1"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
  <mask id="dotMask"><rect width="{W}" height="{H}" fill="url(#dotFade)"/></mask>
  <pattern id="dots" width="16" height="16" patternUnits="userSpaceOnUse"><circle cx="1.5" cy="1.5" r="1" fill="#fff" fill-opacity=".16"/></pattern>
  <linearGradient id="edge" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#c4b5fd" stop-opacity=".55"/><stop offset=".35" stop-color="#fff" stop-opacity=".07"/><stop offset=".7" stop-color="#fff" stop-opacity=".05"/><stop offset="1" stop-color="#67e8f9" stop-opacity=".32"/></linearGradient>
  <linearGradient id="hl" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".55"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <linearGradient id="rankGrad" gradientUnits="userSpaceOnUse" x1="{xs[2]:.1f}" y1="0" x2="{xs[2]+widths[2]:.1f}" y2="0"><stop offset="0" stop-color="#67e8f9"/><stop offset="1" stop-color="#b79bff"/></linearGradient>
  <linearGradient id="brandGrad" gradientUnits="userSpaceOnUse" x1="{tx-220}" y1="0" x2="{tx-16}" y2="0"><stop offset="0" stop-color="#67e8f9"/><stop offset="1" stop-color="#b79bff"/></linearGradient>
  <linearGradient id="ring" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#67e8f9"/><stop offset="1" stop-color="#a78bfa"/></linearGradient>
  <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#303650"/><stop offset="1" stop-color="#0f121b"/></linearGradient>
  <filter id="soft" x="-20%" y="-300%" width="140%" height="700%"><feGaussianBlur stdDeviation="2.6"/></filter>
  <clipPath id="avatarClip"><circle cx="{PAD+30}" cy="70" r="26"/></clipPath>""")

    b('<g clip-path="url(#clip)">')
    b(f'<rect width="{W}" height="{H}" fill="url(#bg)"/>')
    b(f'<rect width="{W}" height="{H}" fill="url(#dots)" mask="url(#dotMask)"/>')
    b(f'<rect width="{W}" height="{H}" fill="url(#glowA)"><animate attributeName="opacity" values=".8;1;.8" dur="10s" repeatCount="indefinite"/></rect>')
    b(f'<rect width="{W}" height="{H}" fill="url(#glowB)"/>')
    b(f'<rect x="40" y="0" width="{W-80}" height="1" fill="url(#hl)"/>')

    # --- header: avatar, name and status on the left, brand on the right
    ax, ay = PAD + 30, 70
    b(f'<circle cx="{ax}" cy="{ay}" r="31" fill="none" stroke="url(#ring)" stroke-width="1.8"/>')
    if avatar:
        b(f'<image href="{avatar}" xlink:href="{avatar}" x="{ax-26}" y="{ay-26}" width="52" height="52" preserveAspectRatio="xMidYMid slice" clip-path="url(#avatarClip)"/>')
    else:
        b(f'<circle cx="{ax}" cy="{ay}" r="26" fill="#10172a"/>')
        b(f'<text x="{ax}" y="{ay+10}" text-anchor="middle" font-family="{SANS}" font-size="28" font-weight="700" fill="url(#ring)">{html.escape(NAME[:1].upper())}</text>')
    hx = PAD + 78
    b(f'<text x="{hx}" y="68" font-family="{SANS}" font-size="32" font-weight="700" letter-spacing="-.5" fill="#f8fafc">{html.escape(NAME)}</text>')
    b(f'<circle cx="{hx+4}" cy="90" r="3.3" fill="#34d399"/>')
    b(f'<circle cx="{hx+4}" cy="90" r="3.3" fill="none" stroke="#34d399" stroke-width="1.3"><animate attributeName="r" values="3.3;9;3.3" dur="2.8s" repeatCount="indefinite"/>'
      '<animate attributeName="stroke-opacity" values=".8;0;.8" dur="2.8s" repeatCount="indefinite"/></circle>')
    stamp = f"Total usage · updated {now.day} {now.strftime('%b')} {now.year}"
    b(f'<text x="{hx+16}" y="95" font-family="{SANS}" font-size="15" fill="{SOFT}">{html.escape(stamp)}</text>')

    b(f'<rect x="{tx}" y="{ty}" width="{tile}" height="{tile}" rx="13" fill="url(#tile)" stroke="#fff" stroke-opacity=".16"/>')
    b(f'<rect x="{tx+1}" y="{ty+1}" width="{tile-2}" height="{tile/2:.0f}" rx="12" fill="#fff" fill-opacity=".05"/>')
    bolt = f"M{tx+26} {ty+9} L{tx+12.5} {ty+26.5} H{tx+22} L{tx+19.5} {ty+37.5} L{tx+33.5} {ty+19.5} H{tx+24} Z"
    b(f'<path d="{bolt}" fill="#fff"/>')
    brand_r = tx - 16
    b(f'<text x="{brand_r}" y="60" text-anchor="end" font-family="{SANS}" font-size="13.5" font-weight="700" letter-spacing="3.4" fill="url(#brandGrad)">TOKENTRACKER</text>')
    b(f'<text x="{brand_r}" y="81" text-anchor="end" font-family="{SANS}" font-size="13.5" fill="{MUTED}">tokentracker.cc</text>')

    # --- metrics
    labels = ["TOKENS", "COST", "RANK"]
    fills = ["#f8fafc", "#f8fafc", "url(#rankGrad)"]
    subs = [data.get("tokens_month"), data.get("cost_month"), None]
    all_defs = []
    for i in range(3):
        if i:
            b(f'<rect x="{xs[i]-gap/2:.1f}" y="{LABEL_Y-24}" width="1" height="{SUB_Y-LABEL_Y+36}" fill="#fff" fill-opacity=".07"/>')
        b(f'<text x="{xs[i]:.1f}" y="{LABEL_Y}" font-family="{SANS}" font-size="13" font-weight="600" letter-spacing="3.2" fill="{SOFT}">{labels[i]}</text>')
        d, g = rolling(values[i], xs[i], VALUE_Y, fs, fills[i], f"r{i}_")
        all_defs.append(d)
        b(g)
        if subs[i]:
            sx = xs[i]
            b(f'<path d="M{sx+1} {SUB_Y-1} l4.2 -6.4 l4.2 6.4 z" fill="#34d399"/>')
            b(f'<text x="{sx+16}" y="{SUB_Y}" font-family="{SANS}" font-size="14" fill="{SOFT}">{html.escape(str(subs[i]))} this month</text>')
        elif i == 2:
            b(f'<text x="{xs[i]:.1f}" y="{SUB_Y}" font-family="{SANS}" font-size="14" fill="{SOFT}">TokenTracker leaderboard</text>')

    # --- top providers
    if prov:
        b(f'<rect x="{panel_x-34}" y="{LABEL_Y-24}" width="1" height="{H-(LABEL_Y-24)-40}" fill="#fff" fill-opacity=".07"/>')
        b(f'<text x="{panel_x}" y="{LABEL_Y}" font-family="{SANS}" font-size="13" font-weight="600" letter-spacing="3.2" fill="{SOFT}">TOP PROVIDERS</text>')
        name_w = max(46.0, min(88.0, max(len(p["name"]) for p in prov) * 8.9))
        bar_x = panel_x + 36 + name_w + 14
        pct_x = panel_x + panel_w
        bar_w = pct_x - 60 - bar_x
        fallback = iter(FALLBACK_COLORS * 2)
        for i, p in enumerate(prov):
            key = str(p.get("key") or "other")
            lo, hi = PROVIDER_COLORS.get(key) or next(fallback)
            cy = LABEL_Y + 32 + i * 36
            gid = f"pg{i}"
            defs.append(f'<linearGradient id="{gid}" x1="0" x2="1"><stop offset="0" stop-color="{lo}"/><stop offset="1" stop-color="{hi}"/></linearGradient>')
            idefs, icon = provider_icon(key, panel_x + ICON_SIZE / 2, cy, f"pi{i}")
            if idefs:
                defs.append(idefs)
            b(icon)
            b(f'<text x="{panel_x+36}" y="{cy+5.5}" font-family="{SANS}" font-size="16" fill="#e8ecf4">{html.escape(p["name"])}</text>')
            fill_w = max(bar_w * p["pct"] / 100.0, 4.0)
            anim = (f'<animate attributeName="width" values="0;{fill_w:.1f};{fill_w:.1f}" keyTimes="0;.1;1" dur="{CYCLE}s" begin="{0.25 + i*0.14:.2f}s" '
                    f'repeatCount="indefinite" calcMode="spline" keySplines=".16 .84 .3 1;0 0 1 1"/>')
            b(f'<rect x="{bar_x:.1f}" y="{cy-3.5}" width="{bar_w:.1f}" height="7" rx="3.5" fill="#fff" fill-opacity=".07"/>')
            b(f'<rect x="{bar_x:.1f}" y="{cy-3.5}" width="{fill_w:.1f}" height="7" rx="3.5" fill="{hi}" opacity=".55" filter="url(#soft)">{anim}</rect>')
            b(f'<rect x="{bar_x:.1f}" y="{cy-3.5}" width="{fill_w:.1f}" height="7" rx="3.5" fill="url(#{gid})">{anim}</rect>')
            b(f'<text x="{pct_x}" y="{cy+5.5}" text-anchor="end" font-family="{SANS}" font-size="15.5" fill="#c3cad9" '
              f'style="font-variant-numeric:tabular-nums">{html.escape(provider_pct(p))}</text>')

    b(f'<rect x=".5" y=".5" width="{W-1}" height="{H-1}" rx="27.5" fill="none" stroke="url(#edge)"/>')
    b('</g></svg>')

    head = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">'
            f'<title id="t">AI Coding Usage</title><desc id="d">{html.escape(summary)}</desc>')
    return head + "<defs>" + "".join(defs) + "".join(all_defs) + "</defs>\n" + "\n".join(body)


def validate_svg(svg):
    """The card is XML: one stray '<' or '&' makes browsers drop the whole image, so check before publishing."""
    ET.fromstring(svg)


def main():
    data = collect()
    now = datetime.datetime.now(datetime.timezone.utc)
    os.makedirs(OUT_DIR, exist_ok=True)
    svg = render(data, now, fetch_avatar())
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
