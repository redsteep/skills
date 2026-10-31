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
    "done": ("done", "good", "✓"),
    "dropped": ("dropped", "muted", "✕"),
}
ORDER = list(ACTIVITY)

CI = {"passed": ("CI passed", "good", "✓"), "failed": ("CI failed", "critical", "✕"),
      "pending": ("CI running", "neutral", "○")}

CSS = """
:root{color-scheme:light;--surface:#fcfcfb;--raised:#ffffff;--line:#e6e5e0;--text:#0b0b0b;
--text-2:#52514e;--muted:#7a7974;--accent:#2a78d6;--good:#0ca30c;--warning:#fab219;
--serious:#ec835a;--critical:#d03b3b;--chip:#f0efec}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--surface:#1a1a19;--raised:#232321;
--line:#383835;--text:#f0efec;--text-2:#c3c2b7;--muted:#8f8e86;--accent:#3987e5;--chip:#2c2c2a}}
*{box-sizing:border-box}
body{margin:0;background:var(--surface);color:var(--text);
font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 48px}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 16px;margin-bottom:20px}
h1{font-size:20px;margin:0;font-weight:600}
h2{font-size:13px;margin:28px 0 10px;font-weight:600;color:var(--text-2);
text-transform:uppercase;letter-spacing:.04em}
.meta{color:var(--text-2)}
.flag{font-weight:600;padding:2px 8px;border-radius:999px;background:var(--chip)}
.flag.critical{color:var(--critical)}.flag.warning{color:var(--text)}
.flag.warning::before,.flag.critical::before{content:"▲ "}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.tile{background:var(--raised);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.tile .label{color:var(--text-2);font-size:13px}
.tile .value{font-size:28px;font-weight:600;margin-top:2px}
.tile .value small{font-size:15px;color:var(--text-2);font-weight:500}
.tile.hero .value{font-size:48px;line-height:1.1}
.meter{display:flex;gap:2px;margin-top:10px;height:8px}
.meter span{flex:1;border-radius:999px;background:var(--chip)}
.meter span.on{background:var(--accent)}
.cards{display:grid;gap:10px}
.need{background:var(--raised);border:1px solid var(--line);border-left:4px solid var(--warning);
border-radius:10px;padding:12px 14px;display:flex;flex-wrap:wrap;gap:4px 16px;align-items:baseline}
.need.critical{border-left-color:var(--critical)}
.need .what{font-weight:600}.need .why{color:var(--text-2)}.need .links{margin-left:auto}
.empty{color:var(--text-2);padding:4px 0}
.table-wrap{overflow-x:auto;background:var(--raised);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;font-weight:600;color:var(--text-2);text-transform:uppercase;letter-spacing:.04em}
tr:last-child td{border-bottom:0}
.sub{color:var(--text-2);font-size:13px}
.nw{white-space:nowrap}
.badge{display:inline-flex;gap:5px;align-items:center;white-space:nowrap;font-size:13px;
padding:1px 8px;border-radius:999px;background:var(--chip);color:var(--text)}
.badge i{font-style:normal}
.badge.good i{color:var(--good)}.badge.warning i{color:var(--warning)}
.badge.critical i{color:var(--critical)}.badge.accent i{color:var(--accent)}
.badge.neutral i,.badge.muted i{color:var(--muted)}.badge.muted{color:var(--text-2)}
.badge.warning{font-weight:600}
ul.log{margin:0;padding:0 0 0 18px;color:var(--text-2)}ul.log li{margin:2px 0}
details summary{cursor:pointer;color:var(--text-2)}
@media (max-width:640px){
.table-wrap{background:none;border:0}
table,tbody,tr,td{display:block}thead{display:none}
tr{background:var(--raised);border:1px solid var(--line);border-radius:10px;margin-bottom:10px;padding:6px 0}
td{border:0;padding:4px 14px;display:flex;gap:12px}
td:empty{display:none}
td::before{content:attr(data-label);flex:0 0 92px;color:var(--text-2);font-size:12px;
text-transform:uppercase;letter-spacing:.04em;padding-top:2px}}
"""

AGE_JS = """
(function(){var at=Date.parse(document.body.dataset.at),stale=%d,paused=%s;
function tick(){var s=Math.max(0,Math.round((Date.now()-at)/1000)),t=s<90?s+"s ago":
s<5400?Math.round(s/60)+" min ago":Math.round(s/3600)+" h ago";
document.getElementById("age").textContent="updated "+t;
document.getElementById("stale").hidden=paused||s<=stale}
if(!isNaN(at)){tick();setInterval(tick,15000)}
document.querySelectorAll("td time").forEach(function(t){var d=new Date(t.getAttribute("datetime"));
if(!isNaN(d))t.textContent=d.toLocaleString([],{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"})})})();
"""


def _badge(label: str, tone: str, icon: str) -> str:
    return f'<span class="badge {tone}"><i aria-hidden="true">{icon}</i>{escape(label)}</span>'


def _link(url: str | None, text: str) -> str:
    return f'<a href="{escape(url)}">{escape(text)}</a>' if url else ""


def _meter(busy: int, wip: int) -> str:
    return '<div class="meter" aria-hidden="true">' + "".join(
        f'<span class="{"on" if i < busy else ""}"></span>' for i in range(max(wip, 1))) + "</div>"


def _tile(label: str, value: str, of: str = "", extra: str = "", hero: bool = False) -> str:
    small = f" <small>/ {escape(of)}</small>" if of else ""
    return (f'<div class="tile{" hero" if hero else ""}"><div class="label">{escape(label)}</div>'
            f'<div class="value">{escape(value)}{small}</div>{extra}</div>')


def _pr_cell(prs: list) -> str:
    out = []
    for p in prs:
        bits = [_link(p.get("url"), f"#{p['number']}") or f"#{p['number']}"]
        if p["state"] == "OPEN":
            if p.get("ci") in CI:
                bits.append(_badge(*CI[p["ci"]]))
            if p.get("conflicting"):
                bits.append(_badge("conflict", "critical", "▲"))
        else:
            bits.append(_badge(p["state"].lower(), "good" if p["state"] == "MERGED" else "muted",
                               "✓" if p["state"] == "MERGED" else "✕"))
        out.append(" ".join(bits))
    return "<br>".join(out)


def _when(iso: str | None) -> str:
    if not iso:
        return ""
    return f'<time datetime="{escape(iso)}">{escape(iso[:16].replace("T", " "))} UTC</time>'


def rows(status: dict) -> list[dict]:
    """Every step worth a row — under way, waiting or queued — then splits, in the order a person
    acts on them: what waits for them first."""
    out = []
    for item in status["items"]:
        name = f"#{item['issue']} {item['name']}" if item.get("issue") is not None else item["name"]
        where = _link(item.get("url"), name) or escape(name)
        if "split" in item:
            split = item["split"]
            act = "working" if split["alive"] else "starting" if split.get("starting") else "queued"
            out.append({"activity": act, "what": where, "step": "split", "prs": "",
                        "review": "", "seen": "", "conversation": split.get("conversation")})
        for s in item["steps"]:
            if s["activity"] in ("done", "dropped", "later"):
                continue
            out.append({"activity": s["activity"], "what": where,
                        "step": f"{s['n']}/{s['total']}" + (f"<div class=sub>{escape(s['name'])}</div>"
                                                                   if s["name"] != item["name"] else ""),
                        "prs": _pr_cell(s["prs"]),
                        "review": f"{s['review_queued']} queued" if s.get("review_queued") else
                                  ("on" if s.get("review_queued") == 0 else ""),
                        "seen": _when(s.get("developer_seen")), "conversation": s.get("conversation")})
    out.sort(key=lambda r: ORDER.index(r["activity"]) if r["activity"] in ORDER else len(ORDER))
    return out


def render(status: dict) -> str:
    cards, issues = status["pools"]["cards"], status["pools"]["issues"]
    attention = status["attention"]
    paused = bool(status.get("paused"))
    tiles = [_tile("Needs you", str(len(attention)), hero=True),
             _tile("Card slots", str(cards["busy"]), str(cards["wip"]), _meter(cards["busy"], cards["wip"])),
             _tile("Issue slots", str(issues["busy"]), str(issues["wip"]), _meter(issues["busy"], issues["wip"]))]
    if issues.get("per_day") is not None:
        tiles.append(_tile("Issue steps today", str(issues.get("today") or 0), str(issues["per_day"]),
                           _meter(issues.get("today") or 0, issues["per_day"])))

    needs = []
    for a in attention:
        critical = a["why"].startswith("failed") or "no worker" in a["why"]
        title = (a.get("title") or "").removeprefix("factory · ")
        needs.append(f'<div class="need{" critical" if critical else ""}">'
                     + (f'<span class="what">{escape(title)}</span>' if title else "")
                     + f'<span class="why">{escape(a["why"])}</span>'
                     + f'<span class="links">{_link(a.get("conversation"), "Open the conversation →")}</span></div>')

    table = rows(status)
    body_rows = "".join(
        f"<tr><td data-label=Doing>{_badge(*ACTIVITY.get(r['activity'], (r['activity'], 'neutral', '·')))}</td>"
        f"<td data-label=What>{r['what']}</td><td data-label=Step>{r['step']}</td>"
        f"<td data-label=PR>{r['prs']}</td><td data-label=Review class=nw>{escape(r['review'])}</td>"
        f"<td data-label='You wrote' class='sub nw'>{r['seen']}</td>"
        f"<td data-label=Worker class=nw>{_link(r['conversation'], 'Open')}</td></tr>" for r in table)
    steps = ('<div class="table-wrap"><table><thead><tr><th>Doing</th><th>What</th><th>Step</th>'
             '<th>PR</th><th>Review</th><th>You last wrote</th><th>Worker</th></tr></thead>'
             f"<tbody>{body_rows}</tbody></table></div>") if table else '<p class="empty">Nothing under way.</p>'

    log = status.get("dispatch") or []
    dispatch = (f'<details{" open" if len(log) <= 8 else ""}><summary>{len(log)} action(s)</summary>'
                '<ul class="log">' + "".join(f"<li>{escape(d)}</li>" for d in log) + "</ul></details>"
                ) if log else '<p class="empty">Nothing to do.</p>'

    at = status.get("at") or ""
    flags = []
    if paused:
        flags.append('<span class="flag warning">paused</span>')
    flags.append('<span class="flag critical" id="stale" hidden>stale — is the timer running?</span>')
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="{REFRESH}">
<title>{"⏸ " if paused else ""}{"(" + str(len(attention)) + ") " if attention else ""}factory</title>
<style>{CSS}</style></head>
<body data-at="{escape(at)}"><main>
<header><h1>factory {escape(str(status.get("version", "")))}</h1>
<span class="meta" id="age">{"as of " + _when(at) if at else ""}</span>{"".join(flags)}</header>
<section class="tiles" aria-label="Slots">{"".join(tiles)}</section>
<h2>Needs you</h2>
<div class="cards">{"".join(needs) or '<p class="empty">Nothing waits for you.</p>'}</div>
<h2>Steps</h2>
{steps}
<h2>Last dispatch</h2>
{dispatch}
</main>
<script>{AGE_JS % (STALE_AFTER, json.dumps(paused))}</script>
</body></html>
"""
