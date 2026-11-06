"""The factory's status as one static HTML page: `render(status)` of the snapshot factory_status
writes. Self-contained — no scripts or styles from anywhere else — and refreshed by the dispatch
that writes it; the page reloads itself every minute and works out its own age, so a page that
stopped being written reads stale rather than current."""

from __future__ import annotations

import json
from html import escape

REFRESH = 60          # seconds between reloads
STALE_AFTER = 10 * 60

# activity → (label, tone, icon). Tone is the status role it wears; a status colour never stands
# alone — the icon and the label say the same.
ACTIVITY = {
    "waits-you": ("waits for you", "warning", "●"),
    "no-worker": ("no worker", "critical", "▲"),
    "waking": ("hearing an event", "neutral", "↻"),
    "waits-ci": ("waits for CI", "neutral", "○"),
    "working": ("working", "accent", "▶"),
    "restarting": ("restarting", "neutral", "↻"),
    "starting": ("starting", "accent", "▷"),
    "queued": ("queued", "muted", "…"),
    "later": ("later", "muted", "·"),
    "on-hold": ("on hold", "muted", "‖"),
    "done": ("done", "good", "✓"),
    "dropped": ("dropped", "muted", "✕"),
}
ORDER = list(ACTIVITY)

CI = {"passed": ("CI passed", "good", "✓"), "failed": ("CI failed", "critical", "✕"),
      "pending": ("CI running", "neutral", "○")}

CSS = """
:root{color-scheme:light;--surface:#f6f5f2;--raised:#ffffff;--line:#e6e5e0;--rule:#eeede8;--text:#0b0b0b;
--text-2:#52514e;--muted:#7a7974;--accent:#2368c2;--on-accent:#ffffff;--link:#1f63b5;--good:#0a6e0a;
--warn-bg:#fff3d1;--warn-text:#7a4f00;--crit-bg:#fbeaea;--crit-text:#a32b2b;--acc-bg:#e7f0fb;
--chip:#efeee9;--strong:#0b0b0b;--on-strong:#ffffff}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--surface:#1a1a19;--raised:#232321;--line:#383835;
--rule:#2f2f2d;--text:#f0efec;--text-2:#c3c2b7;--muted:#8f8e86;--accent:#3987e5;--on-accent:#0b0b0b;
--link:#7cb2f2;--good:#5fd35f;--warn-bg:#3a2f12;--warn-text:#f5c860;--crit-bg:#3d1f1f;--crit-text:#f08f8f;
--acc-bg:#1f2f45;--chip:#2c2c2a;--strong:#f0efec;--on-strong:#0b0b0b}}
*{box-sizing:border-box}
body{margin:0;background:var(--surface);color:var(--text);
font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 48px;display:flex;flex-direction:column;gap:22px}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
header{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px 16px}
.brand{display:flex;align-items:baseline;gap:8px}
h1{font-size:22px;margin:0;font-weight:650;letter-spacing:-.01em}
.version{color:var(--text-2);font-size:13px}
.live{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;font-size:13px;color:var(--text-2)}
.live .dot{width:8px;height:8px;border-radius:999px;background:var(--good)}
.live:has(#stale:not([hidden])) .dot{display:none}
.flag{font-weight:650;font-size:12px;padding:3px 8px;border-radius:999px;text-transform:uppercase;letter-spacing:.02em}
.flag.warning{background:var(--warn-bg);color:var(--warn-text)}
.flag.critical{background:var(--crit-bg);color:var(--crit-text)}
h2{font-size:17px;margin:0;font-weight:650}h2 .n{color:var(--text-2);font-weight:500}
section{display:flex;flex-direction:column;gap:10px}
.slots{display:grid;grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:8px}
.slot{background:var(--raised);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.slot .label{font-size:12px;color:var(--text-2)}
.slot .value{font-size:20px;font-weight:650}.slot .value small{font-size:14px;color:var(--text-2);font-weight:500}
.meter{display:flex;gap:3px;margin-top:6px}
.meter span{flex:1;height:5px;border-radius:999px;background:var(--line)}
.meter span.on{background:var(--accent)}
.needs{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}
.need{background:var(--raised);border:1px solid var(--line);border-radius:14px;padding:14px;
display:flex;flex-direction:column;gap:10px}
.need .top{display:flex;align-items:center;justify-content:space-between;gap:8px}
.kind{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:650;letter-spacing:.02em;
text-transform:uppercase;padding:3px 8px;border-radius:999px;background:var(--warn-bg);color:var(--warn-text)}
.need.critical .kind{background:var(--crit-bg);color:var(--crit-text)}
.need .what{font-weight:600;font-size:16px;overflow-wrap:anywhere}
.need .why{color:var(--text-2);font-size:14px;display:flex;flex-wrap:wrap;gap:4px 10px;overflow-wrap:anywhere}
.actions{display:flex;align-items:center;gap:12px;margin-top:auto}
a.app{flex:1;min-height:44px;display:flex;align-items:center;justify-content:center;border-radius:10px;
background:var(--accent);color:var(--on-accent);font-weight:600;text-decoration:none}
.need.critical a.app{background:var(--strong);color:var(--on-strong)}
a.web{min-height:44px;display:flex;align-items:center;padding:0 6px;font-size:14px}
.list{background:var(--raised);border:1px solid var(--line);border-radius:14px;display:flex;flex-direction:column}
.row{display:flex;align-items:center;gap:12px;padding:10px 14px;min-height:56px;border-bottom:1px solid var(--rule)}
.row:last-child{border-bottom:0}
.ico{width:28px;height:28px;flex:none;border-radius:999px;display:flex;align-items:center;justify-content:center;
background:var(--chip);color:var(--text-2);font-size:13px;font-weight:700}
.ico.accent{background:var(--acc-bg);color:var(--link)}
.ico.critical{background:var(--crit-bg);color:var(--crit-text)}
.ico.good{color:var(--good)}
.row .body{flex:1;min-width:0}
.row .title{display:block;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text)}
.row .sub{display:block;font-size:13px;color:var(--text-2)}
.row .open{min-height:44px;display:flex;align-items:center;padding:0 4px;font-size:14px;white-space:nowrap}
.ci{white-space:nowrap}.ci.good{color:var(--good)}.ci.critical{color:var(--crit-text);font-weight:600}
.empty{color:var(--text-2);margin:0}
details{background:var(--raised);border:1px solid var(--line);border-radius:14px;padding:0 14px;overflow:hidden}
details summary{min-height:48px;display:flex;align-items:center;justify-content:space-between;font-weight:600;
cursor:pointer;list-style:none}
details summary::-webkit-details-marker{display:none}
details summary::after{content:"Show";font-size:13px;color:var(--text-2);font-weight:500}
details[open] summary::after{content:"Hide"}
details .list{border:0;border-radius:0;margin:0 -14px}
details .row{padding:8px 14px;min-height:48px}
ul.log{margin:0;padding:0 0 12px 18px;color:var(--text-2);font-size:14px}ul.log li{margin:2px 0;overflow-wrap:anywhere}
"""

AGE_JS = """
(function(){var at=Date.parse(document.body.dataset.at),stale=%d,paused=%s;
function tick(){var s=Math.max(0,Math.round((Date.now()-at)/1000)),t=s<90?s+"s ago":
s<5400?Math.round(s/60)+" min ago":Math.round(s/3600)+" h ago";
document.getElementById("age").textContent=t;
document.getElementById("stale").hidden=paused||s<=stale}
if(!isNaN(at)){tick();setInterval(tick,15000)}
})();
"""


# What "Add to Home Screen" reads: the page opens full screen, as an app, under this name.
MANIFEST = {
    "name": "factory", "short_name": "factory", "start_url": ".", "scope": ".",
    "display": "standalone", "background_color": "#1a1a19", "theme_color": "#1a1a19",
    "icons": [{"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
              {"src": "apple-touch-icon.png", "sizes": "180x180", "type": "image/png"}],
}


# A decision's kind (the snapshot's `kind`) → its label; critical ones lead and wear red.
KIND = {
    "failed": "Dispatch failed", "no-worker": "No worker", "brief": "Approve brief", "spec": "Approve spec",
    "review": "Review PR", "handoff": "After merge", "question": "Answer",
}
CRITICAL_KINDS = ("failed", "no-worker")
UNDER_WAY = ("waking", "waits-ci", "working", "restarting", "starting")
LATER = ("queued", "later", "on-hold")


def _link(url: str | None, text: str) -> str:
    return f'<a href="{escape(url)}">{escape(text)}</a>' if url else ""


def app_url(url: str) -> str:
    """The same claude.ai page in the Claude desktop app: it answers `claude://claude.ai/<path>`
    as it would the web path, so a session link opens the session there instead of a browser tab."""
    return "claude://" + url.removeprefix("https://") if url.startswith("https://claude.ai/") else url


def _meter(busy: int, wip: int) -> str:
    return '<div class="meter" aria-hidden="true">' + "".join(
        f'<span class="{"on" if i < busy else ""}"></span>' for i in range(max(wip, 1))) + "</div>"


def _slot(label: str, busy: int, of: int) -> str:
    return (f'<div class="slot"><div class="label">{escape(label)}</div>'
            f'<div class="value">{busy}<small> / {of}</small></div>{_meter(busy, of)}</div>')


def _ci(p: dict) -> str:
    """One PR as a link and the one thing about it worth a glance: CI, a conflict, or how it ended."""
    bits = [_link(p.get("url"), f"PR #{p['number']}") or f"PR #{p['number']}"]
    if p["state"] == "OPEN":
        if p.get("ci") in CI:
            label, tone, icon = CI[p["ci"]]
            bits.append(f'<span class="ci {tone}"><span aria-hidden="true">{icon}</span> {label}</span>')
        if p.get("conflicting"):
            bits.append('<span class="ci critical"><span aria-hidden="true">▲</span> conflict</span>')
    else:
        bits.append(f'<span class="ci">{escape(p["state"].lower())}</span>')
    return " ".join(bits)


def _kind(a: dict) -> str:
    """A snapshot from before `kind` existed is read by its `why`, as the page used to."""
    if a.get("kind") in KIND:
        return a["kind"]
    why = a.get("why") or ""
    return ("failed" if why.startswith("failed") else "no-worker" if "no worker" in why
            else "brief" if why.startswith("brief") else "question")


def needs(status: dict) -> list[str]:
    """What waits for the developer, each with the one button that answers it: what is broken
    first, then in the order the dispatch found them."""
    out = []
    for a in sorted(status["attention"], key=lambda a: _kind(a) not in CRITICAL_KINDS):
        kind = _kind(a)
        title = (a.get("title") or "").removeprefix("factory · ")
        label = KIND[kind] + (f" #{a['pr']}" if kind == "review" and a.get("pr") else "")
        why = "".join(f"<span>{bit}</span>" for bit in
                      ([] if a["why"] == "waits for you" else [escape(a["why"])]) + [_ci(p) for p in a.get("prs") or []])
        conv = a.get("conversation")
        actions = (f'<div class="actions"><a class="app" href="{escape(app_url(conv))}">Open in Claude</a>'
                   f'<a class="web" href="{escape(conv)}">web</a></div>') if conv else ""
        out.append(f'<article class="need{" critical" if kind in CRITICAL_KINDS else ""}">'
                   f'<div class="top"><span class="kind">{escape(label)}</span></div>'
                   + (f'<div class="what">{escape(title)}</div>' if title else "")
                   + (f'<div class="why">{why}</div>' if why else "")
                   + actions + "</article>")
    return out


def rows(status: dict) -> list[dict]:
    """Every step worth a row, and every card still being split, in the order a person acts on
    them: what waits for them first."""
    out = []
    for item in status["items"]:
        name = f"#{item['issue']} {item['name']}" if item.get("issue") is not None else item["name"]
        if "split" in item:
            split = item["split"]
            step = {"analysing": "analysing the card", "brief": "brief before you",
                    "approved": "brief approved — splitting"}.get(split.get("phase"), "split")
            out.append({"activity": split["activity"], "name": name, "url": item.get("url"),
                        "sub": [escape(step)], "conversation": split.get("conversation")})
        for s in item["steps"]:
            if s["activity"] in ("done", "dropped"):
                continue
            sub = [f"{s['n']} / {s['total']}" + (f" · {escape(s['name'])}" if s["name"] != item["name"] else "")]
            sub += [_ci(p) for p in s["prs"]]
            if s.get("review_queued"):
                sub.append(f"{s['review_queued']} queued in review")
            out.append({"activity": s["activity"], "name": name, "url": item.get("url"), "sub": sub,
                        "conversation": s.get("conversation")})
    out.sort(key=lambda r: ORDER.index(r["activity"]) if r["activity"] in ORDER else len(ORDER))
    return out


def _row(r: dict) -> str:
    label, tone, icon = ACTIVITY.get(r["activity"], (r["activity"], "neutral", "·"))
    conv = r.get("conversation")
    title = (f'<a class="title" href="{escape(app_url(conv))}">{escape(r["name"])}</a>' if conv
             else f'<span class="title">{escape(r["name"])}</span>')
    card = [f'<a href="{escape(r["url"])}">card</a>'] if r.get("url") else []
    sub = " · ".join(r["sub"] + [escape(label)] + card)
    web = f'<a class="open" href="{escape(conv)}">web</a>' if conv else ""
    return (f'<div class="row"><span class="ico {tone}" aria-hidden="true">{icon}</span>'
            f'<span class="body">{title}<span class="sub">{sub}</span></span>{web}</div>')


def render(status: dict) -> str:
    cards, issues = status["pools"]["cards"], status["pools"]["issues"]
    attention = status["attention"]
    paused = bool(status.get("paused"))
    slots = [_slot("Cards", cards["busy"], cards["wip"]), _slot("Issues", issues["busy"], issues["wip"])]
    if issues.get("per_day") is not None:
        slots.append(_slot("Issue steps today", issues.get("today") or 0, issues["per_day"]))

    need = needs(status)
    table = rows(status)
    now = [r for r in table if r["activity"] not in LATER and r["activity"] not in ("waits-you", "no-worker")]
    later = [r for r in table if r["activity"] in LATER]
    under_way = (f'<div class="list">{"".join(_row(r) for r in now)}</div>' if now
                 else '<p class="empty">Nothing under way.</p>')
    queued = (f'<details><summary><span>Queued &amp; later <span class="n">{len(later)}</span></span></summary>'
              f'<div class="list">{"".join(_row(r) for r in later)}</div></details>') if later else ""

    log = status.get("dispatch") or []
    dispatch = (f'<details><summary><span>Last dispatch <span class="n">{len(log)} action(s)</span></span>'
                '</summary><ul class="log">' + "".join(f"<li>{escape(d)}</li>" for d in log) + "</ul></details>"
                ) if log else ""

    at = status.get("at") or ""
    flags = []
    if paused:
        flags.append('<span class="flag warning">paused</span>')
    flags.append('<span class="flag critical" id="stale" hidden>stale — is the timer running?</span>')
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="{REFRESH}">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="factory">
<meta name="theme-color" content="#f6f5f2" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#1a1a19" media="(prefers-color-scheme: dark)">
<title>{"⏸ " if paused else ""}{"(" + str(len(attention)) + ") " if attention else ""}factory</title>
<style>{CSS}</style></head>
<body data-at="{escape(at)}"><main>
<header><div class="brand"><h1>factory</h1><span class="version">{escape(str(status.get("version", "")))}</span></div>
<div class="live">{"" if paused else '<span class="dot" aria-hidden="true"></span>'}<span id="age">{"as of " + escape(at[:16].replace("T", " ")) + " UTC" if at else ""}</span>{"".join(flags)}</div></header>
<section class="slots" aria-label="Slots">{"".join(slots)}</section>
<section aria-labelledby="needs"><h2 id="needs">Needs you <span class="n">{len(attention)}</span></h2>
{f'<div class="needs">{"".join(need)}</div>' if need else '<p class="empty">Nothing waits for you.</p>'}</section>
<section aria-labelledby="underway"><h2 id="underway">Under way <span class="n">{len(now)}</span></h2>
{under_way}</section>
{queued}
{dispatch}
</main>
<script>{AGE_JS % (STALE_AFTER, json.dumps(paused))}</script>
</body></html>
"""
