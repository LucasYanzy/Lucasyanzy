#!/usr/bin/env python3
"""Render the "AI Coding Usage" card from TokenTracker's public endpoints.

Standard library only. Reads tokens / cost / rank (all time) plus this month's
tokens and cost from the badge endpoint, and the tool split, the models and a
year of daily totals from the public profile endpoint, for one public
TokenTracker profile. Writes dist/ai-usage.svg (the README card) and
dist/ai-usage.json (the same numbers, read by the portfolio page).

Only tokens / cost / rank are required. Everything else is optional: if it is
missing or malformed the card is drawn without that part.

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
MAX_MODELS = 5
MAX_DAYS = 371    # 53 weeks: the most the activity grid can show
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


def fetch_profile():
    """The public profile (period=total): lifetime totals, and the tool split, models and daily totals
    of the trailing year."""
    qs = urllib.parse.urlencode({"user_id": USER_ID, "period": "total"})
    req = urllib.request.Request(f"{PROFILE}?{qs}", headers={"User-Agent": "profile-readme-card/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        profile = json.load(r)
    if not isinstance(profile, dict) or (profile.get("period") or {}).get("kind") != "total":
        raise ValueError("profile endpoint did not return the all-time period")
    return profile


def num(value):
    """A finite, non-negative number, or None."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v >= 0 else None


def parse_providers(profile):
    """Tool split, largest first. `percent` is a fraction of the tokens. More than MAX_PROVIDERS rows
    fold into "Other"."""
    rows = []
    for row in profile.get("by_provider") or []:
        src = str(row.get("source") or "other").lower()
        pct = (num(row.get("percent")) or 0) * 100.0
        if pct > 0:
            rows.append({"key": src, "name": PROVIDER_NAMES.get(src, src.replace("-", " ").title()), "pct": pct,
                         "tokens": int(num(row.get("total_tokens")) or 0)})
    rows = [r for r in rows if r["pct"] >= MIN_SHARE]
    rows.sort(key=lambda r: r["pct"], reverse=True)
    if len(rows) > MAX_PROVIDERS:
        keep, rest = rows[: MAX_PROVIDERS - 1], rows[MAX_PROVIDERS - 1:]
        other, other_tokens = sum(r["pct"] for r in rest), sum(r["tokens"] for r in rest)
        existing = next((r for r in keep if r["key"] == "other"), None)
        if existing:
            existing["pct"] += other
            existing["tokens"] += other_tokens
        else:
            keep.append({"key": "other", "name": "Other", "pct": other, "tokens": other_tokens})
        rows = sorted(keep, key=lambda r: r["pct"], reverse=True)
    return rows


def model_name(raw):
    """A model id as shown: no router prefix ("anthropic/…"), no trailing date stamp ("-20250929")."""
    name = str(raw or "").strip().rsplit("/", 1)[-1]
    name = re.sub(r"[-@]20\d{6}$", "", name)
    return name[:40] if re.match(r"[A-Za-z0-9]", name) else ""


def parse_models(profile):
    """The most used models as a share of all model tokens, largest first, and how many there are."""
    totals = {}
    for row in (profile.get("models") or {}).get("breakdown") or []:
        name, tokens = model_name(row.get("model_name")), num(row.get("total_tokens")) or 0
        if name and tokens > 0:
            totals[name] = totals.get(name, 0) + tokens
    whole = sum(totals.values())
    if whole <= 0:
        return [], 0
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return [{"name": n, "tokens": int(t), "pct": t / whole * 100.0} for n, t in ranked[:MAX_MODELS]], len(ranked)


def parse_daily(profile):
    """Daily token totals of the trailing year as {"start": "YYYY-MM-DD", "tokens": [...]}, one entry per
    calendar day with no gaps, oldest first. None if the profile carries no usable days."""
    by_day = {}
    for cell in profile.get("heatmap") or []:
        try:
            day = datetime.date.fromisoformat(str(cell.get("date")))
        except (ValueError, AttributeError):
            continue
        by_day[day] = int(num(cell.get("total_tokens")) or 0)
    if not by_day:
        return None
    last = max(by_day)
    first = max(min(by_day), last - datetime.timedelta(days=MAX_DAYS - 1))
    tokens = [by_day.get(first + datetime.timedelta(days=i), 0) for i in range((last - first).days + 1)]
    return {"start": first.isoformat(), "tokens": tokens} if any(tokens) else None


def activity(daily):
    """Active days, streaks and the busiest day, all read off the same days the grid shows.
    The current streak may end yesterday: a day that has only just begun does not break it."""
    tokens = daily["tokens"]
    start = datetime.date.fromisoformat(daily["start"])
    longest = run = 0
    for v in tokens:
        run = run + 1 if v > 0 else 0
        longest = max(longest, run)
    current, i = 0, len(tokens) - 1
    if i >= 0 and tokens[i] <= 0:
        i -= 1
    while i >= 0 and tokens[i] > 0:
        current, i = current + 1, i - 1
    best = max(range(len(tokens)), key=lambda k: tokens[k])
    return {
        "active_days": sum(1 for v in tokens if v > 0),
        "window_days": len(tokens),
        "streak": {"current": current, "longest": longest},
        "best_day": {"date": (start + datetime.timedelta(days=best)).isoformat(), "tokens": tokens[best]},
        "tokens_7d": sum(tokens[-7:]),
    }


def parse_profile(profile):
    """Everything the profile adds to the badges. Each part is optional and guarded on its own, so one
    odd field never costs the rest."""
    out = {}

    def part(label, fn):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(f"::warning::{label} unavailable, card drawn without it: {e}")

    def providers():
        rows = parse_providers(profile)
        if rows:
            out["providers"] = rows

    def models():
        rows, count = parse_models(profile)
        if rows:
            out["models"], out["models_count"] = rows, count

    def daily():
        d = parse_daily(profile)
        if d:
            out["daily"] = d
            out.update(activity(d))

    def raw_totals():
        totals = profile.get("totals") or {}
        tokens, cost = num(totals.get("total_tokens")), num(totals.get("estimated_cost_usd"))
        if tokens:
            out["tokens_raw"] = int(tokens)
        if cost is not None:
            out["cost_raw"] = round(cost, 2)

    part("top providers", providers)
    part("models", models)
    part("daily activity", daily)
    part("raw totals", raw_totals)
    return out


def sample_profile():
    """A made-up profile in the endpoint's shape, for AI_USAGE_SAMPLE (no network)."""
    rng = random.Random(7)
    end = datetime.date(2026, 11, 9)
    heat = []
    for i in range(365):
        day = end - datetime.timedelta(days=364 - i)
        ramp = 0.15 + 0.85 * (i / 364) ** 1.6
        quiet = rng.random() < (0.55 - 0.4 * i / 364) or (day.weekday() == 6 and rng.random() < 0.5)
        heat.append({"date": day.isoformat(), "total_tokens": 0 if quiet else int(ramp * rng.lognormvariate(18.6, 0.9))})
    return {
        "period": {"kind": "total"},
        "totals": {"total_tokens": 14_360_000_000, "estimated_cost_usd": 7513.4},
        "by_provider": [{"source": "codex", "percent": 0.426, "total_tokens": 6_117_000_000},
                        {"source": "other", "percent": 0.337, "total_tokens": 4_839_000_000},
                        {"source": "claude", "percent": 0.236, "total_tokens": 3_389_000_000},
                        {"source": "gemini", "percent": 0.001, "total_tokens": 15_000_000}],
        "models": {"breakdown": [
            {"model_name": "gpt-5.5-codex", "total_tokens": 5_220_000_000},
            {"model_name": "claude-opus-4-5-20251101", "total_tokens": 2_410_000_000},
            {"model_name": "kimi-k2-thinking", "total_tokens": 2_950_000_000},
            {"model_name": "anthropic/claude-sonnet-4-5-20250929", "total_tokens": 980_000_000},
            {"model_name": "gpt-5.2", "total_tokens": 900_000_000},
            {"model_name": "deepseek-v3.2", "total_tokens": 1_400_000_000},
            {"model_name": "glm-4.7", "total_tokens": 500_000_000},
            {"model_name": "<synthetic>", "total_tokens": 0}]},
        "heatmap": heat,
    }


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
                **parse_profile(sample_profile())}
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
        data.update(parse_profile(fetch_profile()))
    except Exception as e:  # noqa: BLE001
        print(f"::warning::profile unavailable, card drawn from the badges alone: {e}")
    return data


# ------------------------------------------------------------------ drawing
ADV = {".": .30, ",": .30, "$": .62, "#": .64, "B": .70, "M": .86, "K": .68, "T": .62, "k": .56, "m": .86, "b": .60}
DIGIT = .62
INK, TEXT, SOFT, MUTED = "#f8fafc", "#e8ecf4", "#8b93a7", "#7b8499"
DIM = "#7d879c"   # prefix and unit glyphs ($ # B M K) sit back so the digits carry the number
UP = "#34d399"

# One fixed colour per tool, so a tool keeps its colour whatever its rank. The eight hues are a set checked
# for colour-blind separation on a dark surface; "Other" is a neutral grey. The portfolio page uses the same map.
PROVIDER_COLORS = {
    "codex": "#3987e5",
    "claude": "#d95926",
    "gemini": "#199e70",
    "cursor": "#c98500",
    "copilot": "#d55181",
    "opencode": "#008300",
    "kimi": "#9085e9",
    "deepseek": "#e66767",
    "other": "#6b7690",
}
FALLBACK_COLOR = "#6b7690"   # a tool this file has no colour for is drawn like "Other"; its name still labels it

# Activity grid: one hue, brighter means more. HEAT[0] is a day without usage.
HEAT = ["#141826", "#165a70", "#1187a2", "#25bcd9", "#8af0fd"]


def text_width(value, fs):
    return sum((DIGIT if ch.isdigit() else ADV.get(ch, .62)) * fs for ch in value)


def short(n):
    """Three significant figures with a unit: 1309185720 -> 1.31B, 412000000 -> 412M."""
    n = float(n)
    for div, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= div:
            v = n / div
            return (f"{v:.0f}" if v >= 100 else f"{v:.1f}" if v >= 10 else f"{v:.2f}") + unit
    return str(int(n))


def day_label(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')} {d.year}"


def heat_levels(tokens):
    """0 for a day without usage, otherwise 1-4 by quartile of the days that have some."""
    used = sorted(v for v in tokens if v > 0)
    if not used:
        return [0] * len(tokens)
    cuts = [used[min(len(used) - 1, int(len(used) * q))] for q in (.25, .5, .75)]
    return [0 if v <= 0 else 1 + sum(v > c for c in cuts) for v in tokens]


def numeral(value, x, y, fs, fill=INK):
    """A large figure whose prefix and unit glyphs are dimmed."""
    spans = "".join(html.escape(ch) if ch.isdigit() or ch in ".," else f'<tspan fill="{DIM}">{html.escape(ch)}</tspan>'
                    for ch in value)
    return (f'<text x="{x:.1f}" y="{y}" font-family="{SANS}" font-weight="700" font-size="{fs:.1f}" letter-spacing="-.8" '
            f'fill="{fill}">{spans}</text>')


def provider_pct(p):
    v = p["pct"]
    if v < 0.1:
        return "<0.1%"
    return f"{v:.1f}".rstrip("0").rstrip(".") + "%"


def grow(width, i):
    """Bars draw in once when the card loads. The plain attribute is the final width, so a renderer
    without SMIL shows the finished bar."""
    return (f'<animate attributeName="width" from="0" to="{width:.1f}" dur="{0.8 + i * 0.12:.2f}s" fill="freeze" '
            f'calcMode="spline" keyTimes="0;1" keySplines=".16 .84 .3 1"/>')


ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "assets", "provider-icons")
ICON_SIZE = 20


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
    """Dashboard card. Header, then one row of figures, then (when the profile gave them) a year of daily
    activity with the top models under it, and the tool split with a few highlights beside it. All dynamic
    text is escaped and main() parses the result as XML before anything is published."""
    W, PAD = 1100, 44
    prov = data.get("providers") or []
    models = (data.get("models") or [])[:3]
    daily = data.get("daily")
    label_css = f'font-family="{SANS}" font-size="12" font-weight="600" letter-spacing="2.6" fill="{SOFT}"'

    summary = f'{NAME}: {data["tokens"]} tokens, {data["cost"]} cost, rank {data["rank"]} on TokenTracker'
    if daily:
        summary += (f'. Active on {data["active_days"]} of the last {data["window_days"]} days, current streak '
                    f'{data["streak"]["current"]} days, longest {data["streak"]["longest"]}')
    if prov:
        summary += ". Tools: " + ", ".join(f'{p["name"]} {provider_pct(p)}' for p in prov)
    if models:
        summary += ". Top models: " + ", ".join(f'{m["name"]} {provider_pct(m)}' for m in models)

    # --- geometry
    HEAD_H = 100                      # header ends here
    KPI_LABEL, KPI_VALUE, KPI_SUB = HEAD_H + 34, HEAD_H + 78, HEAD_H + 102
    Y0 = HEAD_H + 124                 # lower band starts here
    RW = 280
    RX = W - PAD - RW                 # right column
    LX2 = RX - 40                     # left column ends here
    LW = LX2 - PAD
    lower = bool(daily or prov or models)
    cols = 53
    pitch = LW / cols
    cell = pitch * 0.8
    grid_top = Y0 + 62
    row_a = max((62 + 7 * pitch + 6) if daily else 0, (60 + (len(prov) - 1) * 28 + 22) if prov else 0)
    row_b = bool(models or daily)
    YB = Y0 + row_a + (8 if row_a else 0)   # second row of the lower band
    H = HEAD_H + 124
    if lower:
        H = int(YB + (22 + 26 + 2 * 24 + 30 if row_b else 14))

    defs = [f"""
  <clipPath id="clip"><rect width="{W}" height="{H}" rx="24"/></clipPath>
  <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0b0e1b"/><stop offset="1" stop-color="#07080e"/></linearGradient>
  <radialGradient id="glow" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate({W*0.78:.0f} -60) scale(640 300)"><stop offset="0" stop-color="#6d5ef5" stop-opacity=".22"/><stop offset="1" stop-color="#4f46e5" stop-opacity="0"/></radialGradient>
  <linearGradient id="edge" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#c4b5fd" stop-opacity=".45"/><stop offset=".35" stop-color="#fff" stop-opacity=".07"/><stop offset=".7" stop-color="#fff" stop-opacity=".05"/><stop offset="1" stop-color="#67e8f9" stop-opacity=".28"/></linearGradient>
  <linearGradient id="accent" x1="0" x2="1"><stop offset="0" stop-color="#67e8f9"/><stop offset="1" stop-color="#b79bff"/></linearGradient>
  <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2a3048"/><stop offset="1" stop-color="#0f121b"/></linearGradient>
  <clipPath id="avatarClip"><circle cx="{PAD+24}" cy="52" r="22"/></clipPath>"""]
    body = []
    b = body.append
    rule = lambda y: b(f'<rect x="{PAD}" y="{y}" width="{W-2*PAD}" height="1" fill="#fff" fill-opacity=".07"/>')

    b('<g clip-path="url(#clip)">')
    b(f'<rect width="{W}" height="{H}" fill="url(#bg)"/>')
    b(f'<rect width="{W}" height="{H}" fill="url(#glow)"/>')

    # --- header: who and what on the left, the source on the right
    ax, ay = PAD + 24, 52
    b(f'<circle cx="{ax}" cy="{ay}" r="25.5" fill="none" stroke="url(#accent)" stroke-width="1.4"/>')
    if avatar:
        b(f'<image href="{avatar}" xlink:href="{avatar}" x="{ax-22}" y="{ay-22}" width="44" height="44" preserveAspectRatio="xMidYMid slice" clip-path="url(#avatarClip)"/>')
    else:
        b(f'<circle cx="{ax}" cy="{ay}" r="22" fill="#10172a"/>')
        b(f'<text x="{ax}" y="{ay+8.5}" text-anchor="middle" font-family="{SANS}" font-size="24" font-weight="700" fill="url(#accent)">{html.escape(NAME[:1].upper())}</text>')
    hx = PAD + 64
    b(f'<text x="{hx}" y="48" font-family="{SANS}" font-size="24" font-weight="700" letter-spacing="-.3" fill="{INK}">{html.escape(NAME)}'
      f'<tspan dx="12" font-size="15" font-weight="400" letter-spacing="0" fill="{SOFT}">AI coding usage</tspan></text>')
    stamp = f"All time · updated {now.day} {now.strftime('%b')} {now.year}"
    b(f'<text x="{hx}" y="72" font-family="{SANS}" font-size="13.5" fill="{MUTED}">{html.escape(stamp)}</text>')

    tile = 36
    tx, ty = W - PAD - tile, 34
    b(f'<rect x="{tx}" y="{ty}" width="{tile}" height="{tile}" rx="10" fill="url(#tile)" stroke="#fff" stroke-opacity=".14"/>')
    bolt = f"M{tx+20.5} {ty+7} L{tx+10} {ty+20.5} H{tx+17.2} L{tx+15.2} {ty+29} L{tx+26} {ty+15.2} H{tx+18.8} Z"
    b(f'<path d="{bolt}" fill="#fff"/>')
    b(f'<text x="{tx-14}" y="49" text-anchor="end" font-family="{SANS}" font-size="12" font-weight="700" letter-spacing="3" fill="url(#accent)">TOKENTRACKER</text>')
    b(f'<text x="{tx-14}" y="68" text-anchor="end" font-family="{SANS}" font-size="12.5" fill="{MUTED}">tokentracker.cc</text>')
    rule(HEAD_H)

    # --- one row of figures
    kpis = [("TOKENS", data["tokens"], data.get("tokens_month"), None),
            ("COST", data["cost"], data.get("cost_month"), None),
            ("RANK", data["rank"], None, "TokenTracker leaderboard")]
    if daily:
        kpis += [("ACTIVE DAYS", str(data["active_days"]), None, f'of the last {data["window_days"]} days'),
                 ("CURRENT STREAK", str(data["streak"]["current"]), None, f'days · longest {data["streak"]["longest"]}')]
    col_w = (W - 2 * PAD) / 5
    fs = 40.0
    widest = max(text_width(v, fs) for _, v, _, _ in kpis)
    if widest > col_w - 40:
        fs = max(26.0, fs * (col_w - 40) / widest)
    for i, (label, value, gain, note) in enumerate(kpis):
        x = PAD + i * col_w
        if i:
            b(f'<rect x="{x-20:.1f}" y="{KPI_LABEL-14}" width="1" height="{KPI_SUB-KPI_LABEL+22}" fill="#fff" fill-opacity=".07"/>')
        b(f'<text x="{x:.1f}" y="{KPI_LABEL}" {label_css}>{label}</text>')
        b(numeral(value, x, KPI_VALUE, fs))
        if gain:
            b(f'<path d="M{x+1:.1f} {KPI_SUB-1} l4 -6 l4 6 z" fill="{UP}"/>')
            b(f'<text x="{x+15:.1f}" y="{KPI_SUB}" font-family="{SANS}" font-size="13" fill="{SOFT}">{html.escape(str(gain))} this month</text>')
        elif note:
            b(f'<text x="{x:.1f}" y="{KPI_SUB}" font-family="{SANS}" font-size="13" fill="{SOFT}">{html.escape(note)}</text>')

    if lower:
        rule(Y0)
        b(f'<rect x="{RX-20}" y="{Y0+18}" width="1" height="{H-Y0-42}" fill="#fff" fill-opacity=".07"/>')

    # --- a year of daily activity
    if daily:
        tokens = daily["tokens"]
        start = datetime.date.fromisoformat(daily["start"])
        levels = heat_levels(tokens)
        offset = start.weekday()                       # weeks run Monday to Sunday, top to bottom
        skip = max(0, (offset + len(tokens) + 6) // 7 - cols) * 7 - offset
        if skip > 0:                                   # more than 53 weeks: drop the oldest
            tokens, levels, start, offset = tokens[skip:], levels[skip:], start + datetime.timedelta(days=skip), 0
        b(f'<text x="{PAD}" y="{Y0+34}" {label_css}>DAILY ACTIVITY · LAST 12 MONTHS</text>')
        r = cell * 0.2
        side = cell - 2 * r
        paths = [[] for _ in HEAT]
        last_label = -9
        for i, level in enumerate(levels):
            c, row = divmod(offset + i, 7)
            x, y = PAD + c * pitch, grid_top + row * pitch
            paths[level].append(f"M{x+r:.1f} {y+r:.1f}h{side:.1f}v{side:.1f}h{-side:.1f}z")
            day = start + datetime.timedelta(days=i)
            if (day.day == 1 or i == 0) and c - last_label >= 3 and c <= cols - 2:
                if i == 0 and day.day > 20:
                    continue                           # a sliver of a month at the left edge gets no name
                b(f'<text x="{x:.1f}" y="{grid_top-9}" font-family="{SANS}" font-size="11.5" fill="{MUTED}">{day.strftime("%b")}</text>')
                last_label = c
        for level, d in enumerate(paths):
            if d:
                b(f'<path d="{"".join(d)}" fill="{HEAT[level]}" stroke="{HEAT[level]}" stroke-width="{2*r:.1f}" stroke-linejoin="round"/>')
        # scale key, right-aligned on the heading line
        kx = LX2 - 34
        b(f'<text x="{LX2}" y="{Y0+34}" text-anchor="end" font-family="{SANS}" font-size="11.5" fill="{MUTED}">More</text>')
        for j, colour in enumerate(reversed(HEAT)):
            b(f'<rect x="{kx - (j+1)*13:.1f}" y="{Y0+24.5}" width="10" height="10" rx="2.2" fill="{colour}"/>')
        b(f'<text x="{kx - 5*13 - 7:.1f}" y="{Y0+34}" text-anchor="end" font-family="{SANS}" font-size="11.5" fill="{MUTED}">Less</text>')

    # --- tools: whose tokens they were
    if prov:
        b(f'<text x="{RX+20}" y="{Y0+34}" {label_css}>TOOLS</text>')
        px = RX + 20
        name_w = max(46.0, min(84.0, max(len(p["name"]) for p in prov) * 8.3))
        bar_x = px + 30 + name_w + 12
        pct_x = W - PAD
        bar_w = pct_x - 54 - bar_x
        for i, p in enumerate(prov):
            key = str(p.get("key") or "other")
            colour = PROVIDER_COLORS.get(key, FALLBACK_COLOR)
            cy = Y0 + 60 + i * 28
            _, icon = provider_icon(key, px + ICON_SIZE / 2, cy, f"pi{i}")
            b(icon)
            b(f'<text x="{px+30}" y="{cy+5}" font-family="{SANS}" font-size="14.5" fill="{TEXT}">{html.escape(p["name"])}</text>')
            fill_w = max(bar_w * p["pct"] / 100.0, 4.0)
            b(f'<rect x="{bar_x:.1f}" y="{cy-3}" width="{bar_w:.1f}" height="6" rx="3" fill="#fff" fill-opacity=".07"/>')
            b(f'<rect x="{bar_x:.1f}" y="{cy-3}" width="{fill_w:.1f}" height="6" rx="3" fill="{colour}">{grow(fill_w, i)}</rect>')
            b(f'<text x="{pct_x}" y="{cy+5}" text-anchor="end" font-family="{SANS}" font-size="14" fill="#c3cad9" '
              f'style="font-variant-numeric:tabular-nums">{html.escape(provider_pct(p))}</text>')

    # --- top models: ranked bars on one baseline, one hue
    if models:
        b(f'<text x="{PAD}" y="{YB+22}" {label_css}>TOP MODELS</text>')
        if data.get("models_count", 0) > len(models):
            b(f'<text x="{PAD+118}" y="{YB+22}" font-family="{SANS}" font-size="12" fill="{MUTED}">of {data["models_count"]} used</text>')
        bar_x, pct_x = PAD + 196, LX2
        bar_w = pct_x - 58 - bar_x
        top = max(m["pct"] for m in models)
        for i, m in enumerate(models):
            cy = YB + 48 + i * 24
            name = m["name"] if len(m["name"]) <= 24 else m["name"][:23] + "…"
            fill_w = max(bar_w * m["pct"] / top, 4.0)
            b(f'<text x="{PAD}" y="{cy+5}" font-family="{SANS}" font-size="14" fill="{TEXT}">{html.escape(name)}</text>')
            b(f'<rect x="{bar_x}" y="{cy-3}" width="{fill_w:.1f}" height="6" rx="3" fill="{HEAT[3]}">{grow(fill_w, i)}</rect>')
            b(f'<text x="{pct_x}" y="{cy+5}" text-anchor="end" font-family="{SANS}" font-size="14" fill="#c3cad9" '
              f'style="font-variant-numeric:tabular-nums">{html.escape(provider_pct(m))}</text>')

    # --- highlights
    if daily:
        b(f'<text x="{RX+20}" y="{YB+22}" {label_css}>HIGHLIGHTS</text>')
        best = data["best_day"]
        facts = [("Busiest day", f'{short(best["tokens"])} · {day_label(best["date"])}'),
                 ("Last 7 days", short(data["tokens_7d"]))]
        if data.get("models_count"):
            facts.append(("Models used", str(data["models_count"])))
        for i, (label, value) in enumerate(facts):
            cy = YB + 48 + i * 24
            b(f'<text x="{RX+20}" y="{cy+5}" font-family="{SANS}" font-size="14" fill="{SOFT}">{label}</text>')
            b(f'<text x="{W-PAD}" y="{cy+5}" text-anchor="end" font-family="{SANS}" font-size="14" fill="{TEXT}">{html.escape(value)}</text>')

    b(f'<rect x=".5" y=".5" width="{W-1}" height="{H-1}" rx="23.5" fill="none" stroke="url(#edge)"/>')
    b('</g></svg>')

    head = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">'
            f'<title id="t">AI Coding Usage</title><desc id="d">{html.escape(summary)}</desc>')
    return head + "<defs>" + "".join(defs) + "</defs>\n" + "\n".join(body)


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
        json.dump({"schema": 2, **data, "updated": now.isoformat(timespec="seconds")}, f, separators=(",", ":"))
    shown = {k: v for k, v in data.items() if k != "daily"}
    print(f"ai-usage.svg written ({len(svg)} bytes): {shown}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        # keep the last good card: report and stop without publishing
        print(f"::warning::AI usage card not updated: {e}")
        sys.exit(1)
