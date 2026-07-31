#!/usr/bin/env python3
"""
Renders assets/telemetry-{dark,light}.svg from live GitHub data.

Run by .github/workflows/telemetry.yml on a schedule.
Standard library only - no pip install step needed in CI.

    python tools/telemetry.py                 # live, uses $GITHUB_TOKEN if present
    python tools/telemetry.py --mock          # offline sample data for local preview
"""
import json
import os
import sys
import urllib.request
import urllib.error
import pathlib
import datetime as dt
from html import escape

USER = os.environ.get("GH_USER", "Ags-Ghafoor601")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT = pathlib.Path(os.environ.get("ASSET_DIR", "assets"))
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"

THEMES = {
    "dark": dict(bg="#0D1117", border="#1F2937", accent="#22D3EE", accent2="#A78BFA",
                 text="#E6EDF3", muted="#8B949E", dim="#4B5563", track="#161B22"),
    "light": dict(bg="#FFFFFF", border="#D0D7DE", accent="#0891B2", accent2="#7C3AED",
                  text="#0D1117", muted="#57606A", dim="#8C959F", track="#EAEEF2"),
}

# Languages get a stable colour so the chart reads the same every day.
LANG_COLOR = {
    "Python": "#3572A5", "C++": "#F34B7D", "TypeScript": "#3178C6",
    "JavaScript": "#F1E05A", "HTML": "#E34C26", "CSS": "#563D7C",
    "C": "#555555", "Jupyter Notebook": "#DA5B0B", "Assembly": "#6E4C13",
    "Shell": "#89E051", "Dockerfile": "#384D54", "SCSS": "#C6538C",
}
FALLBACK = ["#22D3EE", "#A78BFA", "#34D399", "#FBBF24", "#F87171", "#60A5FA"]

# Long language names get a readable short form rather than a mid-word chop.
LANG_SHORT = {"Jupyter Notebook": "Jupyter", "Objective-C": "Obj-C",
              "Vim Script": "VimScript", "Emacs Lisp": "E-Lisp"}


def shorten(text, limit):
    text = LANG_SHORT.get(text, text)
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def api(path):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": f"{USER}-profile-telemetry",
                 **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {})},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def graphql_contributions():
    """Contribution calendar. Needs a token; returns None when unavailable."""
    if not TOKEN:
        return None
    q = ("query($login:String!){user(login:$login){contributionsCollection"
         "{contributionCalendar{totalContributions weeks{contributionDays"
         "{date contributionCount weekday}}}}}}")
    body = json.dumps({"query": q, "variables": {"login": USER}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql", data=body,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
                 "User-Agent": f"{USER}-profile-telemetry"})
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    cal = (payload.get("data") or {}).get("user", {}) \
        .get("contributionsCollection", {}).get("contributionCalendar")
    return cal


def collect():
    user = api(f"/users/{USER}")
    repos, page = [], 1
    while True:
        batch = api(f"/users/{USER}/repos?per_page=100&page={page}&type=owner&sort=pushed")
        repos += batch
        if len(batch) < 100:
            break
        page += 1

    owned = [r for r in repos if not r.get("fork")]
    stars = sum(r.get("stargazers_count", 0) for r in owned)

    langs = {}
    for r in owned:
        try:
            for lang, byts in api(f"/repos/{USER}/{r['name']}/languages").items():
                langs[lang] = langs.get(lang, 0) + byts
        except urllib.error.HTTPError:
            continue

    recent = sorted(owned, key=lambda r: r.get("pushed_at") or "", reverse=True)[:3]

    try:
        calendar = graphql_contributions()
    except Exception as exc:
        print(f"::warning::contribution calendar unavailable ({exc})")
        calendar = None

    return {
        "calendar": calendar,
        "repos": user.get("public_repos", len(owned)),
        "stars": stars,
        "followers": user.get("followers", 0),
        "langs": langs,
        "recent": [{"name": r["name"], "pushed": r.get("pushed_at", ""),
                    "lang": r.get("language") or ""} for r in recent],
    }


def mock():
    return {
        "repos": 23, "stars": 23, "followers": 7,
        "langs": {"Python": 512000, "C++": 388000, "TypeScript": 240000,
                  "JavaScript": 190000, "HTML": 96000, "C": 48000},
        "recent": [{"name": "calderr-ai-2026", "pushed": "2026-07-29T10:02:00Z", "lang": "Python"},
                   {"name": "AI-Portfolio", "pushed": "2026-07-24T18:40:00Z", "lang": "TypeScript"},
                   {"name": "Movies-Manager", "pushed": "2026-07-11T09:15:00Z", "lang": "C++"}],
        "calendar": None,
    }


def ago(iso):
    if not iso:
        return "-"
    try:
        then = dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return "-"
    d = (dt.datetime.now(dt.timezone.utc) - then).days
    if d <= 0:
        return "today"
    if d == 1:
        return "1 day ago"
    if d < 30:
        return f"{d} days ago"
    if d < 365:
        return f"{d // 30} mo ago"
    return f"{d // 365} yr ago"


def render(data, t):
    W, H = 1000, 286
    top = sorted(data["langs"].items(), key=lambda kv: -kv[1])[:6]
    total = sum(v for _, v in top) or 1

    p = []
    a = p.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
      f'role="img" aria-label="Live GitHub telemetry for {USER}">')
    a('<defs><filter id="tglow" x="-50%" y="-50%" width="200%" height="200%">'
      '<feGaussianBlur stdDeviation="2" result="b"/>'
      '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
      f'<pattern id="tdots" width="14" height="14" patternUnits="userSpaceOnUse">'
      f'<circle cx="1" cy="1" r="1" fill="{t["dim"]}" opacity="0.25"/></pattern></defs>')

    a(f'<rect width="{W}" height="{H}" rx="10" fill="{t["bg"]}"/>')
    a(f'<rect width="{W}" height="{H}" rx="10" fill="url(#tdots)"/>')

    a(f'<g font-family="{MONO}">')

    # header bar
    a(f'<circle cx="40" cy="40" r="3.5" fill="{t["accent"]}" filter="url(#tglow)">'
      f'<animate attributeName="opacity" values="1;0.2;1" dur="1.8s" repeatCount="indefinite"/></circle>')
    a(f'<text x="54" y="44" font-size="11" letter-spacing="4.5" fill="{t["accent"]}">LIVE TELEMETRY</text>')
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%d %b %Y %H:%M UTC").upper()
    a(f'<text x="960" y="44" font-size="10" letter-spacing="1.6" fill="{t["dim"]}" '
      f'text-anchor="end">LAST SYNC &#183; {stamp}</text>')
    a(f'<line x1="40" y1="58" x2="960" y2="58" stroke="{t["border"]}" stroke-width="1"/>')

    # ── left: counters ───────────────────────────────────────────────────────
    cells = [(data["repos"], "PUBLIC REPOS"), (data["stars"], "TOTAL STARS"),
             (data["followers"], "FOLLOWERS")]
    for i, (val, label) in enumerate(cells):
        x = 40 + i * 148
        a(f'<g opacity="0"><animate attributeName="opacity" values="0;1" dur="0.5s" '
          f'begin="{0.15 * i:.2f}s" fill="freeze"/>')
        a(f'<text x="{x}" y="112" font-size="38" font-weight="700" fill="{t["text"]}">{val}</text>')
        a(f'<text x="{x}" y="132" font-size="9.5" letter-spacing="2.2" fill="{t["muted"]}">{label}</text>')
        a('</g>')

    # ── left: recent pushes ──────────────────────────────────────────────────
    a(f'<text x="40" y="176" font-size="10" letter-spacing="3.5" fill="{t["dim"]}">MOST RECENT PUSHES</text>')
    for i, r in enumerate(data["recent"]):
        y = 202 + i * 24
        name = escape(shorten(r["name"], 30))
        a(f'<g opacity="0"><animate attributeName="opacity" values="0;1" dur="0.5s" '
          f'begin="{0.5 + 0.12 * i:.2f}s" fill="freeze"/>')
        a(f'<rect x="40" y="{y - 9}" width="3" height="12" fill="{t["accent"]}" opacity="0.8"/>')
        a(f'<text x="52" y="{y}" font-size="11.5" fill="{t["text"]}">{name}</text>')
        a(f'<text x="440" y="{y}" font-size="10" fill="{t["dim"]}" text-anchor="end">{ago(r["pushed"])}</text>')
        a('</g>')

    a(f'<line x1="470" y1="80" x2="470" y2="252" stroke="{t["border"]}" stroke-width="1"/>')

    # ── right: language frequency ────────────────────────────────────────────
    a(f'<text x="504" y="90" font-size="10" letter-spacing="3.5" fill="{t["dim"]}">'
      f'LANGUAGE FREQUENCY &#183; BY BYTES COMMITTED</text>')
    bx0, bx1 = 640, 912
    for i, (lang, byts) in enumerate(top):
        y = 118 + i * 25
        pct = byts / total
        w = max(3.0, pct * (bx1 - bx0))
        col = LANG_COLOR.get(lang, FALLBACK[i % len(FALLBACK)])
        a(f'<text x="504" y="{y + 4}" font-size="11" fill="{t["muted"]}">{escape(shorten(lang, 16))}</text>')
        a(f'<rect x="{bx0}" y="{y - 5}" width="{bx1 - bx0}" height="9" rx="4.5" fill="{t["track"]}"/>')
        a(f'<rect x="{bx0}" y="{y - 5}" width="0" height="9" rx="4.5" fill="{col}">'
          f'<animate attributeName="width" from="0" to="{w:.1f}" dur="1.1s" '
          f'begin="{0.3 + 0.09 * i:.2f}s" fill="freeze" calcMode="spline" '
          f'keySplines="0.16 1 0.3 1"/></rect>')
        a(f'<text x="960" y="{y + 4}" font-size="10.5" fill="{t["muted"]}" '
          f'text-anchor="end">{pct * 100:.1f}%</text>')

    a('</g>')
    a(f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="10" fill="none" '
      f'stroke="{t["border"]}" stroke-width="1"/>')
    a('</svg>')
    return "\n".join(p)



def render_contributions(cal, t):
    """Custom contribution grid - our palette, our layout, animated column by column."""
    CELL, GAP = 12.0, 3.0
    PITCH = CELL + GAP
    LEFT, TOP = 78.0, 74.0

    weeks = (cal or {}).get("weeks") or []
    weeks = weeks[-53:]
    total = (cal or {}).get("totalContributions", 0)

    counts = [d["contributionCount"] for w in weeks for d in w["contributionDays"]]
    peak = max(counts) if counts else 0
    # 4 intensity buckets above zero, scaled to this person's own peak
    steps = [max(1, round(peak * f)) for f in (0.12, 0.30, 0.55, 0.80)]
    ramp = ["#0E2F3A", "#0E7490", "#0891B2", "#22D3EE", "#A5F3FC"] if t["bg"] == "#0D1117" \
        else ["#EAEEF2", "#A5E4F0", "#38BDF8", "#0891B2", "#075985"]

    def level(n):
        if n <= 0:
            return 0
        for i, s_ in enumerate(steps):
            if n <= s_:
                return i + 1
        return 4

    W = int(LEFT + 53 * PITCH + 40)
    H = int(TOP + 7 * PITCH + 52)
    p_ = []
    a = p_.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
      f'role="img" aria-label="Contribution activity, {total} contributions in the last year">')
    a(f'<defs><pattern id="cdots" width="14" height="14" patternUnits="userSpaceOnUse">'
      f'<circle cx="1" cy="1" r="1" fill="{t["dim"]}" opacity="0.22"/></pattern></defs>')
    a(f'<rect width="{W}" height="{H}" rx="10" fill="{t["bg"]}"/>')
    a(f'<rect width="{W}" height="{H}" rx="10" fill="url(#cdots)"/>')
    a(f'<g font-family="{MONO}">')

    a(f'<circle cx="40" cy="40" r="3.5" fill="{t["accent"]}">'
      f'<animate attributeName="opacity" values="1;0.2;1" dur="1.8s" repeatCount="indefinite"/></circle>')
    a(f'<text x="54" y="44" font-size="11" letter-spacing="4.5" fill="{t["accent"]}">SIGNAL LOG</text>')
    a(f'<text x="{W - 40}" y="44" font-size="11" letter-spacing="1.6" fill="{t["muted"]}" '
      f'text-anchor="end">{total} CONTRIBUTIONS &#183; LAST 12 MONTHS</text>')
    a(f'<line x1="40" y1="58" x2="{W - 40}" y2="58" stroke="{t["border"]}" stroke-width="1"/>')

    # month ruler
    seen = set()
    for wi, w in enumerate(weeks):
        d0 = w["contributionDays"][0]["date"]
        mon = d0[:7]
        if mon in seen:
            continue
        seen.add(mon)
        if int(d0[8:10]) > 7:
            continue
        label = dt.datetime.strptime(d0, "%Y-%m-%d").strftime("%b").upper()
        a(f'<text x="{LEFT + wi * PITCH:.1f}" y="{TOP - 8:.1f}" font-size="8.5" '
          f'letter-spacing="1.2" fill="{t["dim"]}">{label}</text>')

    for di, label in ((1, "MON"), (3, "WED"), (5, "FRI")):
        a(f'<text x="{LEFT - 12:.1f}" y="{TOP + di * PITCH + CELL - 2.5:.1f}" font-size="8.5" '
          f'letter-spacing="1.2" fill="{t["dim"]}" text-anchor="end">{label}</text>')

    for wi, w in enumerate(weeks):
        x = LEFT + wi * PITCH
        delay = 0.25 + wi * 0.014
        a(f'<g opacity="0"><animate attributeName="opacity" values="0;1" dur="0.32s" '
          f'begin="{delay:.3f}s" fill="freeze"/>')
        for d in w["contributionDays"]:
            y = TOP + d["weekday"] * PITCH
            n = d["contributionCount"]
            a(f'<rect x="{x:.1f}" y="{y:.1f}" width="{CELL}" height="{CELL}" rx="2.5" '
              f'fill="{ramp[level(n)]}"><title>{d["date"]}: {n}</title></rect>')
        a('</g>')

    # legend
    ly = TOP + 7 * PITCH + 22
    a(f'<text x="{LEFT}" y="{ly + 9:.1f}" font-size="8.5" letter-spacing="1.4" fill="{t["dim"]}">LESS</text>')
    for i, c in enumerate(ramp):
        a(f'<rect x="{LEFT + 40 + i * 16:.1f}" y="{ly:.1f}" width="12" height="12" rx="2.5" fill="{c}"/>')
    a(f'<text x="{LEFT + 128:.1f}" y="{ly + 9:.1f}" font-size="8.5" letter-spacing="1.4" fill="{t["dim"]}">MORE</text>')
    a(f'<text x="{W - 40}" y="{ly + 9:.1f}" font-size="8.5" letter-spacing="1.4" fill="{t["dim"]}" '
      f'text-anchor="end">PEAK {peak}/DAY</text>')

    a('</g>')
    a(f'<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="10" fill="none" '
      f'stroke="{t["border"]}" stroke-width="1"/>')
    a('</svg>')
    return "\n".join(p_)


def mock_calendar():
    import random
    random.seed(7)
    start = dt.date.today() - dt.timedelta(days=371)
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)
    weeks, total = [], 0
    for w in range(53):
        days = []
        for d in range(7):
            date = start + dt.timedelta(days=w * 7 + d)
            n = 0 if random.random() < 0.42 else random.randint(1, 14)
            total += n
            days.append({"date": date.isoformat(), "contributionCount": n, "weekday": d})
        weeks.append({"contributionDays": days})
    return {"totalContributions": total, "weeks": weeks}


def main():
    use_mock = "--mock" in sys.argv
    try:
        data = mock() if use_mock else collect()
    except Exception as exc:                      # never fail the workflow over a flaky API
        print(f"::warning::telemetry fetch failed ({exc}); falling back to sample data")
        data = mock()

    cal = data.get("calendar")
    if not cal:
        print("::warning::no contribution calendar; rendering sample grid")
        cal = mock_calendar()

    OUT.mkdir(parents=True, exist_ok=True)
    for name, t in THEMES.items():
        (OUT / f"telemetry-{name}.svg").write_text(render(data, t), encoding="utf-8")
        (OUT / f"contributions-{name}.svg").write_text(render_contributions(cal, t), encoding="utf-8")
        print(f"wrote telemetry-{name}.svg  contributions-{name}.svg")


if __name__ == "__main__":
    main()
