#!/usr/bin/env python3
"""Render the profile's GitHub stats, streak and top-languages cards from the GitHub GraphQL API.

Standard library only, so it never depends on a third-party card service. Writes into OUT_DIR:
  github-stats.svg   stars, commits, PRs, issues, contributed-to, and a rank ring
  github-streak.svg  total contributions, current streak, longest streak
  top-langs.svg      most used languages across the user's own (non-fork) repositories
  github-cards.json  the numbers the cards were drawn from

Environment:
  GITHUB_TOKEN   token for the GraphQL API (the workflow's own token is enough: public data only)
  CARD_LOGIN     whose cards to draw (defaults to the repository owner)
  CARDS_SAMPLE=1 draw fixed sample numbers, no network
  CARDS_DATA     path to a github-cards.json to draw from instead of the API

The rank uses the formula from github-readme-stats (MIT), and the icons are GitHub Octicons (MIT).
"""
import datetime
import json
import math
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from html import escape

LOGIN = os.environ.get("CARD_LOGIN") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "LucasYanzy"
OUT_DIR = os.environ.get("OUT_DIR", "dist")
API = "https://api.github.com/graphql"
LANGS = 8

BG, BORDER = "#0a0a0f", "#0b3a40"
CYAN, PURPLE = "#00f3ff", "#bd00ff"
TEXT, MUTED, DIM, WHITE = "#c9d1d9", "#8a8f98", "#6b7280", "#ffffff"
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Sans-Serif"


# ------------------------------------------------------------------ data
def graphql(query, variables):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is not set")
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "profile-readme-cards/1.0",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.load(r)
    if out.get("errors"):
        raise RuntimeError(json.dumps(out["errors"])[:600])
    return out["data"]


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(now):
    year_ago = now - datetime.timedelta(days=365)
    profile = graphql("""
      query($login: String!, $from: DateTime!, $to: DateTime!) {
        user(login: $login) {
          name login createdAt
          followers { totalCount }
          pullRequests { totalCount }
          issues { totalCount }
          contributionsCollection(from: $from, to: $to) {
            totalCommitContributions
            totalPullRequestReviewContributions
          }
          repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]) { totalCount }
        }
      }""", {"login": LOGIN, "from": iso(year_ago), "to": iso(now)})["user"]
    if not profile:
        raise RuntimeError(f"no GitHub user {LOGIN!r}")

    stars, langs, after = 0, {}, None
    while True:
        page = graphql("""
          query($login: String!, $after: String) {
            user(login: $login) {
              repositories(first: 100, after: $after, ownerAffiliations: OWNER) {
                nodes {
                  stargazerCount isFork
                  languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name color } } }
                }
                pageInfo { hasNextPage endCursor }
              }
            }
          }""", {"login": LOGIN, "after": after})["user"]["repositories"]
        for repo in page["nodes"]:
            stars += repo["stargazerCount"]
            if repo["isFork"]:
                continue
            for edge in repo["languages"]["edges"]:
                name = edge["node"]["name"]
                entry = langs.setdefault(name, {"name": name, "color": edge["node"]["color"] or "#858585", "size": 0})
                entry["size"] += edge["size"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    # the contribution calendar, one aliased window per calendar year (a window may span a year at most)
    created = datetime.datetime.strptime(profile["createdAt"], "%Y-%m-%dT%H:%M:%SZ")
    windows = []
    for year in range(created.year, now.year + 1):
        start = max(created, datetime.datetime(year, 1, 1))
        end = min(now, datetime.datetime(year, 12, 31, 23, 59, 59))
        windows.append((f"y{year}", start, end))
    parts = "\n".join(
        f'{alias}: contributionsCollection(from: "{iso(a)}", to: "{iso(b)}") '
        "{ contributionCalendar { weeks { contributionDays { date contributionCount } } } }"
        for alias, a, b in windows)
    cal = graphql(f"query($login: String!) {{ user(login: $login) {{ {parts} }} }}", {"login": LOGIN})["user"]
    days = {}
    for alias, _, _ in windows:
        for week in cal[alias]["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                # windows do not overlap, but a calendar may pad its edge weeks: never count a day twice
                days[d["date"]] = max(days.get(d["date"], 0), d["contributionCount"])

    cc = profile["contributionsCollection"]
    return {
        "login": profile["login"],
        "name": profile["name"] or profile["login"],
        "stars": stars,
        "commits": cc["totalCommitContributions"],
        "prs": profile["pullRequests"]["totalCount"],
        "issues": profile["issues"]["totalCount"],
        "reviews": cc["totalPullRequestReviewContributions"],
        "contributed_to": profile["repositoriesContributedTo"]["totalCount"],
        "followers": profile["followers"]["totalCount"],
        "languages": sorted(langs.values(), key=lambda l: -l["size"]),
        "days": dict(sorted(days.items())),
    }


def sample(now):
    days, d = {}, datetime.date(2023, 6, 20)
    while d <= now.date():
        n = d.toordinal()
        days[d.isoformat()] = (n * 7919 % 13) % 6 if (n * 31 % 7) < 3 else 0
        d += datetime.timedelta(days=1)
    return {
        "login": LOGIN, "name": "Lucas Yan", "stars": 3, "commits": 214, "prs": 26, "issues": 2, "reviews": 0,
        "contributed_to": 3, "followers": 4,
        "languages": [{"name": "HTML", "color": "#e34c26", "size": 420000}, {"name": "Python", "color": "#3572A5", "size": 160000},
                      {"name": "C++", "color": "#f34b7d", "size": 90000}, {"name": "JavaScript", "color": "#f1e05a", "size": 70000},
                      {"name": "Java", "color": "#b07219", "size": 52000}, {"name": "CSS", "color": "#663399", "size": 30000},
                      {"name": "C", "color": "#555555", "size": 12000}, {"name": "Shell", "color": "#89e051", "size": 4000},
                      {"name": "Makefile", "color": "#427819", "size": 900}],
        "days": days,
    }


# ------------------------------------------------------------------ numbers
def rank(d):
    """github-readme-stats' rank: a weighted mix of CDFs, lower percentile is better."""
    exp_cdf = lambda x: 1 - 2 ** -x
    log_cdf = lambda x: x / (1 + x)
    weights = 2 + 3 + 1 + 1 + 4 + 1
    score = (2 * exp_cdf(d["commits"] / 250) + 3 * exp_cdf(d["prs"] / 50) + 1 * exp_cdf(d["issues"] / 25)
             + 1 * exp_cdf(d["reviews"] / 2) + 4 * log_cdf(d["stars"] / 50) + 1 * log_cdf(d["followers"] / 10))
    percentile = (1 - score / weights) * 100
    for limit, level in zip([1, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100], ["S", "A+", "A", "A-", "B+", "B", "B-", "C+", "C"]):
        if percentile <= limit:
            return level, percentile
    return "C", percentile


def streaks(days, today):
    """Total, first contribution, current and longest streak. Today with nothing yet does not break the streak."""
    dates = sorted(datetime.date.fromisoformat(k) for k in days)
    if not dates:
        return {"total": 0, "first": None, "current": (0, today, today), "longest": (0, today, today)}
    count = lambda d: days.get(d.isoformat(), 0)
    today = min(today, dates[-1])   # the calendar may end a day early, depending on time zones
    total = sum(days.values())
    first = next((d for d in dates if count(d) > 0), None)

    longest, run, run_start = (0, today, today), 0, None
    for d in dates:
        if count(d) > 0:
            run_start = d if run == 0 else run_start
            run += 1
            if run > longest[0]:
                longest = (run, run_start, d)
        else:
            run = 0

    end = today if count(today) > 0 else today - datetime.timedelta(days=1)
    cur, d = 0, end
    while count(d) > 0:
        cur += 1
        d -= datetime.timedelta(days=1)
    current = (cur, end - datetime.timedelta(days=cur - 1), end) if cur else (0, today, today)
    return {"total": total, "first": first, "current": current, "longest": longest}


def kfmt(n):
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def day(d, today):
    return d.strftime("%b ") + str(d.day) + ("" if d.year == today.year else d.strftime(", %Y"))


def span(start, end, today):
    if start == end:
        return day(start, today)
    return f"{day(start, today)} - {day(end, today)}"


# ------------------------------------------------------------------ drawing
ICONS = {  # GitHub Octicons, 16px
    "star": "M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Zm0 2.445L6.615 5.5a.75.75 0 0 1-.564.41l-3.097.45 2.24 2.184a.75.75 0 0 1 .216.664l-.528 3.084 2.769-1.456a.75.75 0 0 1 .698 0l2.77 1.456-.53-3.084a.75.75 0 0 1 .216-.664l2.24-2.183-3.096-.45a.75.75 0 0 1-.564-.41L8 2.694Z",
    "commit": "M11.93 8.5a4.002 4.002 0 0 1-7.86 0H.75a.75.75 0 0 1 0-1.5h3.32a4.002 4.002 0 0 1 7.86 0h3.32a.75.75 0 0 1 0 1.5Zm-1.43-.75a2.5 2.5 0 1 0-5 0 2.5 2.5 0 0 0 5 0Z",
    "pr": "M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.25 2.25 0 0 1 1.5 3.25Zm5.677-.177L9.573.677A.25.25 0 0 1 10 .854V2.5h1A2.5 2.5 0 0 1 13.5 5v5.628a2.251 2.251 0 1 1-1.5 0V5a1 1 0 0 0-1-1h-1v1.646a.25.25 0 0 1-.427.177L7.177 3.427a.25.25 0 0 1 0-.354ZM3.75 2.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm0 9.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm8.25.75a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Z",
    "issue": "M8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3ZM8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0Z",
    "repo": "M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z",
}
FLAME = ("M12 1.5c.7 3.4-1.1 5.3-2.9 7.2C7.4 10.5 5.8 12.3 5.8 15.2c0 3.8 2.8 6.8 6.2 6.8s6.2-3 6.2-6.9"
         "c0-2.5-1.1-4.3-2.5-5.7.2 1.7-.5 3-1.8 3.6.5-3.7-.6-7.6-1.9-11.5Zm0 13c-1.2 1.2-2 2.2-2 3.6 0 1.3 1 2.4 2 2.4"
         "s2-1.1 2-2.4c0-1.4-.8-2.4-2-3.6Z")

KEYFRAMES = """
  @keyframes fade { from { opacity: 0 } to { opacity: 1 } }
  @keyframes rise { from { opacity: 0; transform: translateY(6px) } to { opacity: 1; transform: none } }
  @keyframes pop { from { opacity: 0; transform: scale(.6) } to { opacity: 1; transform: scale(1) } }
  @media (prefers-reduced-motion: reduce) { * { animation-duration: 0s !important; animation-delay: 0s !important } }"""


def frame(w, h, title, desc, style, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" fill="none" '
            f'role="img" aria-labelledby="t d">\n<title id="t">{escape(title)}</title>\n<desc id="d">{escape(desc)}</desc>\n'
            f"<style>{style}{KEYFRAMES}\n</style>\n"
            f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="11.5" fill="{BG}" stroke="{BORDER}"/>\n'
            f"{body}\n</svg>\n")


def stats_svg(d):
    level, pct = rank(d)
    rows = [("star", "Total Stars Earned", d["stars"]), ("commit", "Total Commits (last year)", d["commits"]),
            ("pr", "Total PRs", d["prs"]), ("issue", "Total Issues", d["issues"]),
            ("repo", "Contributed to (last year)", d["contributed_to"])]
    r = 40
    circ = 2 * math.pi * r
    progress = max(0.02, min(1, (100 - pct) / 100))
    style = f"""
  .header {{ font: 600 18px {FONT}; fill: {CYAN}; animation: fade .8s ease-in-out forwards }}
  .stat {{ font: 600 14px {FONT}; fill: {TEXT} }}
  .row {{ opacity: 0; animation: rise .45s ease-out forwards }}
  .icon {{ fill: {CYAN} }}
  .grade {{ font: 800 24px {FONT}; fill: {TEXT}; opacity: 0; transform-box: fill-box; transform-origin: center;
           animation: pop .4s .9s ease-out forwards }}
  .ring-bg {{ stroke: {PURPLE}; stroke-opacity: .2; stroke-width: 6 }}
  .ring {{ stroke: {PURPLE}; stroke-width: 6; stroke-linecap: round; stroke-dasharray: {circ:.2f};
          stroke-dashoffset: {circ:.2f}; animation: draw 1.1s .3s ease-in-out forwards }}
  @keyframes draw {{ to {{ stroke-dashoffset: {circ * (1 - progress):.2f} }} }}"""
    body = [f'<text class="header" x="25" y="35">{escape(d["name"])}\'s GitHub Stats</text>', '<g transform="translate(25, 62)">']
    for i, (icon, label, value) in enumerate(rows):
        body.append(
            # the position sits on the outer group: an animated CSS transform would override it
            f'  <g transform="translate(0, {i * 25})"><g class="row" style="animation-delay: {300 + i * 140}ms">'
            f'<svg class="icon" x="0" y="-13" width="16" height="16" viewBox="0 0 16 16"><path d="{ICONS[icon]}"/></svg>'
            f'<text class="stat" x="25" y="0">{label}:</text><text class="stat" x="225" y="0">{kfmt(value)}</text></g></g>')
    body.append("</g>")
    body.append(f'<g transform="translate(400, 98)">'
                f'<circle class="ring-bg" r="{r}"/>'
                f'<circle class="ring" r="{r}" transform="rotate(-90)"/>'
                f'<text class="grade" x="0" y="0" text-anchor="middle" dominant-baseline="central">{level}</text></g>')
    desc = ", ".join(f"{label}: {value}" for _, label, value in rows) + f". Rank {level}."
    return frame(495, 195, f"{d['name']}'s GitHub Stats", desc, style, "\n".join(body))


def streak_svg(d, today):
    s = streaks(d["days"], today)
    total_range = f"{day(s['first'], today)} - Present" if s["first"] else "No contributions yet"
    cur, lng = s["current"], s["longest"]
    cur_range = span(cur[1], cur[2], today)
    lng_range = span(lng[1], lng[2], today) if lng[0] else "-"
    style = f"""
  .num {{ font: 700 28px {FONT}; fill: {WHITE} }}
  .label {{ font: 400 14px {FONT}; fill: {MUTED} }}
  .label-hot {{ font: 700 14px {FONT}; fill: {CYAN} }}
  .dates {{ font: 400 12px {FONT}; fill: {DIM} }}
  .col {{ opacity: 0; animation: rise .5s ease-out forwards }}
  .ring {{ stroke: {CYAN}; stroke-width: 5 }}
  .flame {{ fill: {PURPLE}; opacity: 0; transform-box: fill-box; transform-origin: center bottom;
           animation: pop .45s 1s ease-out forwards }}"""
    body = f"""<line x1="165" y1="28" x2="165" y2="170" stroke="{BORDER}"/>
<line x1="330" y1="28" x2="330" y2="170" stroke="{BORDER}"/>
<g class="col" style="animation-delay: 300ms">
  <text class="num" x="82.5" y="79" text-anchor="middle">{kfmt(s['total'])}</text>
  <text class="label" x="82.5" y="114" text-anchor="middle">Total Contributions</text>
  <text class="dates" x="82.5" y="140" text-anchor="middle">{escape(total_range)}</text>
</g>
<mask id="gap"><rect width="495" height="195" fill="white"/><circle cx="247.5" cy="32" r="13" fill="black"/></mask>
<g class="col" style="animation-delay: 600ms">
  <circle class="ring" cx="247.5" cy="71" r="40" mask="url(#gap)"/>
  <text class="num" x="247.5" y="81" text-anchor="middle">{cur[0]}</text>
  <text class="label-hot" x="247.5" y="140" text-anchor="middle">Current Streak</text>
  <text class="dates" x="247.5" y="165" text-anchor="middle">{escape(cur_range)}</text>
</g>
<svg x="236.5" y="20" width="22" height="22" viewBox="0 0 24 24"><path class="flame" fill-rule="evenodd" d="{FLAME}"/></svg>
<g class="col" style="animation-delay: 900ms">
  <text class="num" x="412.5" y="79" text-anchor="middle">{lng[0]}</text>
  <text class="label" x="412.5" y="114" text-anchor="middle">Longest Streak</text>
  <text class="dates" x="412.5" y="140" text-anchor="middle">{escape(lng_range)}</text>
</g>"""
    desc = (f"{s['total']} total contributions ({total_range}). Current streak {cur[0]} days ({cur_range}). "
            f"Longest streak {lng[0]} days ({lng_range}).")
    return frame(495, 195, f"{d['name']}'s GitHub streak", desc, style, body), s


def langs_svg(d):
    langs = d["languages"][:LANGS]
    total = sum(l["size"] for l in langs) or 1
    for l in langs:
        l["pct"] = l["size"] * 100 / total
    rows = math.ceil(len(langs) / 2)
    h = max(120, 90 + rows * 25)
    style = f"""
  .header {{ font: 600 18px {FONT}; fill: {CYAN}; animation: fade .8s ease-in-out forwards }}
  .lang {{ font: 400 12px {FONT}; fill: {TEXT} }}
  .item {{ opacity: 0; animation: rise .4s ease-out forwards }}
  .seg {{ transform-box: fill-box; transform-origin: left center; transform: scaleX(0);
          animation: grow .7s ease-out forwards }}
  @keyframes grow {{ to {{ transform: scaleX(1) }} }}"""
    body = ['<text class="header" x="25" y="35">Most Used Languages</text>',
            '<clipPath id="bar"><rect x="25" y="52" width="445" height="8" rx="4"/></clipPath>',
            f'<rect x="25" y="52" width="445" height="8" rx="4" fill="{BORDER}"/>', '<g clip-path="url(#bar)">']
    x = 25.0
    for i, l in enumerate(langs):
        w = 445 * l["pct"] / 100
        body.append(f'  <rect class="seg" style="animation-delay: {200 + i * 90}ms" x="{x:.2f}" y="52" '
                    f'width="{w + 0.5:.2f}" height="8" fill="{escape(l["color"])}"/>')
        x += w
    body.append("</g>")
    for i, l in enumerate(langs):
        col, row = i % 2, i // 2
        body.append(f'<g transform="translate({25 + col * 230}, {85 + row * 25})"><g class="item" style="animation-delay: {450 + i * 80}ms">'
                    f'<circle cx="5" cy="-4" r="5" fill="{escape(l["color"])}"/>'
                    f'<text class="lang" x="17" y="0">{escape(l["name"])} {l["pct"]:.2f}%</text></g></g>')
    desc = ", ".join(f"{l['name']} {l['pct']:.1f}%" for l in langs)
    return frame(495, h, "Most used languages", desc, style, "\n".join(body))


def validate(svg, name):
    try:
        ET.fromstring(svg)
    except ET.ParseError as e:
        raise SystemExit(f"{name} is not valid XML: {e}")


# ------------------------------------------------------------------ main
def main():
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)
    if os.environ.get("CARDS_DATA"):
        with open(os.environ["CARDS_DATA"]) as f:
            data = json.load(f)
    elif os.environ.get("CARDS_SAMPLE") == "1":
        data = sample(now)
    else:
        data = fetch(now)
    today = now.date()
    stats = stats_svg(data)
    streak, s = streak_svg(data, today)
    langs = langs_svg(data)
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, svg in [("github-stats.svg", stats), ("github-streak.svg", streak), ("top-langs.svg", langs)]:
        validate(svg, name)
        with open(os.path.join(OUT_DIR, name), "w") as f:
            f.write(svg)
    level, pct = rank(data)
    summary = {k: data[k] for k in ("login", "name", "stars", "commits", "prs", "issues", "reviews", "contributed_to", "followers")}
    summary.update({
        "rank": level, "percentile": round(pct, 2),
        "total_contributions": s["total"], "first_contribution": s["first"].isoformat() if s["first"] else None,
        "current_streak": [s["current"][0], s["current"][1].isoformat(), s["current"][2].isoformat()],
        "longest_streak": [s["longest"][0], s["longest"][1].isoformat(), s["longest"][2].isoformat()],
        "languages": [{"name": l["name"], "pct": round(l.get("pct", 0), 2)} for l in data["languages"][:LANGS]],
        "rendered_at": now.isoformat() + "Z",
    })
    with open(os.path.join(OUT_DIR, "github-cards.json"), "w") as f:
        json.dump(summary, f, indent=2)
    # the full data, so a card can be redrawn locally with CARDS_DATA
    with open(os.path.join(OUT_DIR, "github-data.json"), "w") as f:
        json.dump(data, f)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # keep the last good cards: the workflow skips publishing on a non-zero exit
        print(f"::warning::GitHub cards not updated: {e}", file=sys.stderr)
        sys.exit(1)
