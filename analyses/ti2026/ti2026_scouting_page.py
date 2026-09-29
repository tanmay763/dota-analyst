"""Render a TI 2026 draft board (HTML) from analyses/ti2026/ti2026_scouting.py output.

One team  -> a column of player cards, position 1 to 5.
Two teams -> a head-to-head board laid out by position: the two opposing players
             for each role sit side by side, with the pool they are actually
             fighting over directly beneath them. Each position carries its own
             contest index: every hero whose most-played position in the
             tournament is that role, ranked by picks + bans from both sides.
             Opens with a first-phase ban prediction scored from the data.

    uv run analyses/ti2026/ti2026_scouting_page.py analyses/ti2026/out/gf_scouting_YYYY-MM-DD.json \
        --title "Grand Final Draft Board" -o analyses/ti2026/out/gf_board_YYYY-MM-DD.html

Provenance: ti2026.context.json.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

ROLE = {1: "Carry", 2: "Mid", 3: "Offlane", 4: "Soft support", 5: "Hard support"}
HUES = [
    {"l": "#0B7C82", "li": "#065C61", "lw": "#E0EEEE", "d": "#41B3B8", "di": "#7FD2D5", "dw": "#16302F"},
    {"l": "#8A4A2F", "li": "#6B3720", "lw": "#F3E8E2", "d": "#D08C63", "di": "#E2AC8B", "dw": "#2E211A"},
]

ap = argparse.ArgumentParser()
ap.add_argument("json_path")
ap.add_argument("--title", required=True)
ap.add_argument("--eyebrow", default="The International 2026 &middot; Shanghai")
ap.add_argument("--lede", default="")
ap.add_argument("--note", default="", help="coverage caveat shown in the footer")
ap.add_argument("-o", "--out", required=True)
args = ap.parse_args()

d = json.loads(Path(args.json_path).read_text())
esc = lambda s: html.escape(str(s))
label = lambda t: t.get("alias") or t["team"]
teams = d["teams"]
by_pos = d.get("contested_by_pos") or {}
versus = len(teams) == 2 and bool(by_pos)


def rec(w: int, n: int) -> str:
    return f'{w}<span class="dash">-</span>{n - w}'


def player_card(p: dict, idx: int, team: dict, show_team: bool, hl: str = "h3") -> str:
    rows = []
    for h in p["heroes"]:
        form = "".join(f'<i class="sq {"w" if x else "l"}"></i>' for x in h["form"])
        tone = "hot" if (h["n"] >= 3 and h["w"] == h["n"]) else (
               "cold" if (h["n"] >= 3 and h["w"] == 0) else "")
        rows.append(
            f'<tr class="{tone}"><th scope="row">{esc(h["hero"])}</th>'
            f'<td class="num">{h["n"]}</td><td class="num rec">{rec(h["w"], h["n"])}</td>'
            f'<td><span class="sqs">{form}</span></td>'
            f'<td class="num">{h["gpm"]}</td>'
            f'<td class="num">{h["k"]}<span class="sl">/</span>{h["d"]}'
            f'<span class="sl">/</span>{h["a"]}</td></tr>')
    sig = max(p["heroes"], key=lambda h: (h["n"], h["w"]))
    imp = f'+{p["imp"]}' if p["imp"] > 0 else f'{p["imp"]}'
    badge = (f'<span class="tchip">{esc(label(team))}</span>' if show_team
             else f'<span class="posmark">{p["pos"]}</span>')
    return f"""<section class="card t{idx}">
 <header class="card-hd">
  {badge}
  <div class="who"><{hl}>{esc(p['player'])}</{hl}><p class="role">{ROLE[p['pos']]}</p></div>
  <dl class="agg">
   <div><dt>Record</dt><dd>{p['wins']}-{p['games']-p['wins']}</dd></div>
   <div><dt>Heroes</dt><dd>{len(p['heroes'])}</dd></div>
   <div><dt>GPM</dt><dd>{p['gpm']}</dd></div>
   <div><dt>IMP</dt><dd class="{'pos' if p['imp']>0 else 'neg'}">{imp}</dd></div>
  </dl>
 </header>
 <p class="sig">Most drafted <strong>{esc(sig['hero'])}</strong> &middot; {rec(sig['w'], sig['n'])} in {sig['n']}</p>
 <div class="tw"><table>
  <thead><tr><th scope="col">Hero</th><th scope="col" class="num">N</th>
  <th scope="col" class="num">W-L</th><th scope="col">Form</th>
  <th scope="col" class="num">GPM</th><th scope="col" class="num">K/D/A</th></tr></thead>
  <tbody>{''.join(rows)}</tbody></table></div>
</section>"""


def contest_table(rows: list[dict], a: dict, b: dict, scale: int, limit: int = 12) -> str:
    """Contest index for one position: picks and bans from both sides, ranked."""
    if not rows:
        return '<p class="none">Neither side has picked or banned a hero in this role.</p>'
    shown = rows[:limit]
    trs = []
    for r in shown:
        pw, bw = 100 * r["picks"] / scale, 100 * r["bans"] / scale
        tags = ""
        if r["picks"] == 0:
            tags += ' <span class="tag ban">ban only</span>'
        if r.get("flex"):
            tags += ' <span class="tag flex">flex</span>'
        trs.append(
            f'<tr><th scope="row">{esc(r["hero"])}{tags}</th>'
            f'<td class="num">{r["a_n"]}</td>'
            f'<td class="num rec">{rec(r["a_w"], r["a_n"]) if r["a_n"] else "&mdash;"}</td>'
            f'<td class="num ban{" on" if r["a_ban"] else ""}">{r["a_ban"]}</td>'
            f'<td class="num sep">{r["b_n"]}</td>'
            f'<td class="num rec">{rec(r["b_w"], r["b_n"]) if r["b_n"] else "&mdash;"}</td>'
            f'<td class="num ban{" on" if r["b_ban"] else ""}">{r["b_ban"]}</td>'
            f'<td class="num tot">{r["contest"]}</td>'
            f'<td class="barcell"><span class="bar">'
            f'<i class="seg p" style="width:{pw:.1f}%"></i>'
            f'<i class="seg b" style="width:{bw:.1f}%"></i></span></td></tr>')
    more = (f'<p class="more">{len(shown)} of {len(rows)} heroes in this role, '
            f'by contest</p>' if len(rows) > limit else "")
    return f"""<div class="tw"><table class="ctab idx">
 <thead><tr><th scope="col">Hero</th>
  <th scope="col" class="num c0" colspan="3">{esc(label(a))}</th>
  <th scope="col" class="num c1" colspan="3">{esc(label(b))}</th>
  <th scope="col" class="num" colspan="2">Contest</th></tr>
 <tr class="sub"><th></th><th class="num">Picks</th><th class="num">W-L</th><th class="num">Bans</th>
  <th class="num sep">Picks</th><th class="num">W-L</th><th class="num">Bans</th>
  <th class="num">Total</th><th></th></tr></thead>
 <tbody>{''.join(trs)}</tbody></table></div>{more}"""


def prediction_block(pred: dict, a: dict, b: dict) -> str:
    """First-phase ban shortlist per side, with the score's components exposed."""
    if not pred:
        return ""
    w = pred["weights"]
    sgames = pred.get("series_games") or 0
    cols = []
    for i, t in enumerate((a, b)):
        rows = pred["first_phase"].get(t["team"], [])[:6]
        top = max((r["score"] for r in rows), default=1) or 1
        sg = pred.get("series_games") or 0
        trs = "".join(
            f'<tr><th scope="row">{esc(r["hero"])}</th>'
            + (f'<td class="num ser{" on" if r.get("series_n") else ""}">'
               f'{r.get("series_n", 0)}/{sg}</td>' if sg else "")
            + f'<td class="num">{r["base"]:.2f}</td>'
            f'<td class="num">{r["own"]:.2f}</td>'
            f'<td class="num">{r["threat"]:.2f}</td>'
            f'<td class="barcell"><span class="bar solo">'
            f'<i class="seg s" style="width:{100*r["score"]/top:.1f}%"></i></span></td></tr>'
            for r in rows)
        cols.append(f"""<div class="predcol t{i}">
 <p class="predhd"><span class="swatch"></span>{esc(label(t))} bans</p>
 <div class="tw"><table class="ctab">
  <thead><tr><th scope="col">Hero</th>
   {'<th scope="col" class="num">Series</th>' if sg else ''}
   <th scope="col" class="num">Base</th>
   <th scope="col" class="num">Own</th><th scope="col" class="num">Threat</th>
   <th scope="col">Score</th></tr></thead>
  <tbody>{trs}</tbody></table></div></div>""")
    return f"""<section class="predsec">
 <header class="band"><h2>Predictions</h2>
  <span class="bandmeta">first phase &middot; {pred['slots']} bans</span></header>
 <p class="lede">The opening seven bans, scored per side.
 {'<strong>Series</strong> is first-phase bans in the head-to-head so far and carries '
  + str(int(w.get('in_series', 0)*100)) + '% of the score &mdash; in a specific matchup it '
  'beats any tournament prior. ' if sgames else ''}<strong>Base</strong> is how often the
 hero is first-phase banned across the tournament, <strong>own</strong> is how often this
 team does it, <strong>threat</strong> is how much the opponent drafts it weighted by their
 results on it. A stated heuristic, not a model &mdash; read the components, not the rank.</p>
 <div class="predgrid">{''.join(cols)}</div>
</section>"""


body = []
if versus:
    a, b = teams
    pa = {p["pos"]: p for p in a["players"]}
    pb = {p["pos"]: p for p in b["players"]}
    by_pos = d.get("contest_by_pos") or {}
    scale = max((r["contest"] for rows in by_pos.values() for r in rows), default=1)
    for pos in range(1, 6):
        rows = by_pos.get(str(pos), [])
        cards = ""
        if pos in pa:
            cards += player_card(pa[pos], 0, a, True, "h4")
        if pos in pb:
            cards += player_card(pb[pos], 1, b, True, "h4")
        top = rows[0]["hero"] if rows else ""
        body.append(f"""<section class="posrow">
 <header class="band"><span class="bandnum">{pos}</span><h2>{ROLE[pos]}</h2>
  <span class="bandmeta">{('most contested &middot; ' + esc(top)) if top else ''}</span></header>
 <h3 class="sub-hd">Contest index<span class="sub-meta">{len(rows)} heroes &middot; picks + bans</span></h3>
 {contest_table(rows, a, b, scale)}
 <h3 class="sub-hd">Hero pools<span class="sub-meta">every hero drafted at TI15</span></h3>
 <div class="pair">{cards}</div>
</section>""")

    loose = by_pos.get("none") or []
    if loose:
        body.append(f"""<section class="posrow">
 <header class="band"><h2>No position on record</h2>
  <span class="bandmeta">banned, never picked by anyone</span></header>
 {contest_table(loose, a, b, scale, limit=20)}
</section>""")
    body.append(prediction_block(d.get("predictions") or {}, a, b))
else:
    for idx, t in enumerate(teams):
        alias = f' <span class="orgname">Stratz: {esc(t["team"])}</span>' if t.get("alias") else ""
        cards = "".join(player_card(p, idx, t, False) for p in t["players"])
        body.append(f"""<section class="team t{idx}">
 <header class="team-hd"><h2>{esc(label(t))}{alias}</h2></header>
 <div class="grid">{cards}</div></section>""")

strip = "".join(
    f"""<div class="tsum t{i}"><span class="swatch"></span>
     <div><p class="tname">{esc(label(t))}</p>
      <p class="trec">{t['wins']}&ndash;{t['losses']} <span class="tsub">
      {round(100*t['wins']/t['games'])}% over {t['games']} games</span></p></div></div>"""
    for i, t in enumerate(teams))

hue_light = "".join(f"--t{i}:{HUES[i%2]['l']}; --t{i}-ink:{HUES[i%2]['li']}; --t{i}-wash:{HUES[i%2]['lw']};"
                    for i in range(len(teams)))
hue_dark = "".join(f"--t{i}:{HUES[i%2]['d']}; --t{i}-ink:{HUES[i%2]['di']}; --t{i}-wash:{HUES[i%2]['dw']};"
                   for i in range(len(teams)))
cov = d["coverage"]
lede = args.lede or ("Every hero each player has drafted at TI15, with results in the order "
                     "they were played. Rails mark heroes perfect or winless on three games or more.")

page = f"""<title>{esc(args.title)}</title>
<style>
:root {{
  --bg:#F2F4F4; --panel:#FFFFFF; --ink:#12201F; --ink-2:#4A5E5D; --ink-3:#7B8C8B;
  --line:#DCE3E2; --line-2:#EDF1F0;
  --win:#3F7A4E; --loss:#A8574A; --win-sq:#57986A; --loss-sq:#C58379;
  --hot:#F0F6F3; --cold:#FBF1EF; {hue_light}
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg:#0E1717; --panel:#152020; --ink:#E6EDEC; --ink-2:#9FB3B1; --ink-3:#6E8281;
  --line:#243333; --line-2:#1C2827;
  --win:#79BE8B; --loss:#D8907F; --win-sq:#5E9E72; --loss-sq:#B0705F;
  --hot:#152524; --cold:#231B1A; {hue_dark}
}} }}
:root[data-theme="dark"] {{
  --bg:#0E1717; --panel:#152020; --ink:#E6EDEC; --ink-2:#9FB3B1; --ink-3:#6E8281;
  --line:#243333; --line-2:#1C2827;
  --win:#79BE8B; --loss:#D8907F; --win-sq:#5E9E72; --loss-sq:#B0705F;
  --hot:#152524; --cold:#231B1A; {hue_dark}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font-size:15px; line-height:1.5;
  font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; -webkit-font-smoothing:antialiased; }}
.wrap {{ max-width:1240px; margin:0 auto; padding:clamp(20px,4vw,52px) clamp(14px,3vw,32px) 64px; }}
.num,.rec,.agg dd,.trec {{ font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
  font-variant-numeric:tabular-nums; }}
header.top {{ display:flex; flex-direction:column; gap:16px; padding-bottom:20px; border-bottom:2px solid var(--ink); }}
.eyebrow {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11px;
  letter-spacing:.16em; text-transform:uppercase; color:var(--ink-3); margin:0; }}
h1 {{ margin:0; font-size:clamp(29px,5vw,48px); line-height:1.03; letter-spacing:-.025em;
  font-weight:800; text-wrap:balance; }}
.lede {{ margin:0; color:var(--ink-2); max-width:66ch; }}
.strip {{ display:flex; flex-wrap:wrap; gap:14px; margin:22px 0 6px; }}
.tsum {{ flex:1 1 240px; display:flex; align-items:center; gap:12px; padding:13px 16px;
  background:var(--panel); border:1px solid var(--line); border-radius:3px; }}
.tsum.t0 {{ --tcol:var(--t0); --tink:var(--t0-ink); }}
.tsum.t1 {{ --tcol:var(--t1); --tink:var(--t1-ink); }}
.swatch {{ flex:none; width:5px; align-self:stretch; background:var(--tcol); border-radius:2px; }}
.tname {{ margin:0; font-weight:700; font-size:16px; letter-spacing:-.01em; color:var(--tink); }}
.trec {{ margin:1px 0 0; font-weight:700; font-size:17px; }}
.tsub {{ font-weight:400; font-size:11.5px; color:var(--ink-3); letter-spacing:.02em; }}
.posrow, .crosspos {{ margin-top:34px; }}
.band {{ display:flex; align-items:center; gap:11px; padding-bottom:9px; margin-bottom:14px;
  border-bottom:2px solid var(--ink); }}
.bandnum {{ flex:none; width:26px; height:26px; display:grid; place-items:center; background:var(--ink);
  color:var(--bg); border-radius:2px; font-weight:700; font-size:14px;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
.band h2 {{ margin:0; font-size:clamp(18px,2.4vw,23px); letter-spacing:-.02em; font-weight:750; flex:1 1 auto; }}
.bandmeta {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:10.5px;
  letter-spacing:.11em; text-transform:uppercase; color:var(--ink-3); }}
.pair, .grid {{ display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(340px,1fr)); }}
.team {{ margin-top:34px; }}
.team-hd h2 {{ margin:0 0 14px; font-size:26px; letter-spacing:-.02em; }}
.orgname {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:10.5px;
  letter-spacing:.1em; text-transform:uppercase; color:var(--ink-3); font-weight:400; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:3px;
  display:flex; flex-direction:column; overflow:hidden; border-top:3px solid var(--tcol); }}
.card.t0 {{ --tcol:var(--t0); --tink:var(--t0-ink); --twash:var(--t0-wash); }}
.card.t1 {{ --tcol:var(--t1); --tink:var(--t1-ink); --twash:var(--t1-wash); }}
.card-hd {{ display:flex; align-items:flex-start; gap:12px; padding:14px 17px 12px;
  border-bottom:1px solid var(--line); flex-wrap:wrap; }}
.tchip {{ flex:none; padding:4px 8px; background:var(--twash); color:var(--tink); border-radius:2px;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:10px; font-weight:600;
  letter-spacing:.09em; text-transform:uppercase; }}
.posmark {{ flex:none; width:32px; height:32px; display:grid; place-items:center; background:var(--tcol);
  color:#fff; border-radius:2px; font-weight:700; font-size:16px;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
.who {{ flex:1 1 auto; min-width:0; }}
.who h3 {{ margin:0; font-size:20px; letter-spacing:-.02em; font-weight:700; overflow-wrap:anywhere; }}
.role {{ margin:1px 0 0; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:10.5px;
  letter-spacing:.13em; text-transform:uppercase; color:var(--ink-3); }}
.agg {{ display:flex; gap:15px; margin:0; flex:1 1 100%; padding-top:4px; }}
.agg div {{ display:flex; flex-direction:column; }}
.agg dt {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:9.5px;
  letter-spacing:.12em; text-transform:uppercase; color:var(--ink-3); margin:0; }}
.agg dd {{ margin:0; font-weight:700; font-size:14px; }}
.agg dd.pos {{ color:var(--win); }} .agg dd.neg {{ color:var(--ink-2); }}
.sig {{ margin:0; padding:8px 17px; background:var(--twash); color:var(--tink); font-size:12.5px;
  border-bottom:1px solid var(--line); }}
.sig strong {{ color:var(--ink); }}
.tw {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
thead th {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:9.5px;
  letter-spacing:.11em; text-transform:uppercase; color:var(--ink-3); font-weight:500;
  text-align:left; padding:9px 10px; border-bottom:1px solid var(--line); white-space:nowrap; }}
thead th.num {{ text-align:right; }}
tbody th {{ text-align:left; font-weight:600; padding:7px 10px; white-space:nowrap; }}
tbody td {{ padding:7px 10px; white-space:nowrap; }}
td.num {{ text-align:right; color:var(--ink-2); }}
td.rec {{ color:var(--ink); font-weight:600; }}
.dash,.sl {{ color:var(--ink-3); padding:0 1px; }}
tbody tr {{ border-bottom:1px solid var(--line-2); }}
tbody tr:last-child {{ border-bottom:0; }}
tr.hot {{ background:var(--hot); }} tr.hot th {{ box-shadow:inset 3px 0 0 var(--win); }}
tr.cold {{ background:var(--cold); }} tr.cold th {{ box-shadow:inset 3px 0 0 var(--loss); }}
.sqs {{ display:inline-flex; gap:2px; }}
.sq {{ width:8px; height:13px; border-radius:1px; display:block; }}
.sq.w {{ background:var(--win-sq); }} .sq.l {{ background:var(--loss-sq); }}
.ctab {{ background:var(--panel); border:1px solid var(--line); }}
.ctab.inrow {{ margin-top:14px; }}
.ctab thead th.c0 {{ color:var(--t0-ink); border-bottom:2px solid var(--t0); }}
.ctab thead th.c1 {{ color:var(--t1-ink); border-bottom:2px solid var(--t1); }}
.ctab thead tr.sub th {{ border-bottom:1px solid var(--line); }}
td.ban {{ color:var(--ink-3); }}
td.ban.on {{ color:var(--loss); font-weight:600; }}
.sep {{ border-left:1px solid var(--line); }}
td.tot {{ font-weight:700; color:var(--ink); }}
.tag.flex {{ color:var(--ink-3); border-color:var(--line); }}
.more {{ margin:8px 0 0; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:10.5px;
  letter-spacing:.08em; text-transform:uppercase; color:var(--ink-3); }}
.tag {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:9px; font-weight:500;
  letter-spacing:.08em; text-transform:uppercase; color:var(--loss); border:1px solid var(--loss);
  border-radius:2px; padding:1px 4px; margin-left:6px; vertical-align:1px; }}
.sub-hd {{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap;
  margin:20px 0 10px; font-size:13px; font-weight:700; letter-spacing:.02em; color:var(--ink); }}
.sub-hd:first-of-type {{ margin-top:14px; }}
.sub-meta {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:10px;
  letter-spacing:.11em; text-transform:uppercase; color:var(--ink-3); font-weight:400; }}
.predsec {{ margin-top:40px; padding-top:8px; }}
.predgrid {{ display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); margin-top:16px; }}
.predcol {{ background:var(--panel); border:1px solid var(--line); border-radius:3px; overflow:hidden; }}
.predcol.t0 {{ --tcol:var(--t0); --tink:var(--t0-ink); }}
.predcol.t1 {{ --tcol:var(--t1); --tink:var(--t1-ink); }}
.predhd {{ display:flex; align-items:center; gap:9px; margin:0; padding:11px 14px;
  border-bottom:1px solid var(--line); font-weight:700; font-size:14px; color:var(--tink); }}
.predhd .swatch {{ width:4px; height:15px; align-self:auto; background:var(--tcol); border-radius:2px; }}
.bar.solo {{ background:var(--line-2); }}
td.ser {{ color:var(--ink-3); }}
td.ser.on {{ color:var(--ink); font-weight:700; }}
.seg.s {{ background:var(--tcol); }}
.predcol .barcell {{ width:38%; min-width:96px; }}
.zeropick {{ margin-top:14px; padding:12px 14px; background:var(--panel);
  border:1px solid var(--line); border-radius:3px; display:flex; gap:14px;
  align-items:baseline; flex-wrap:wrap; }}
.zlab {{ margin:0; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:10px;
  letter-spacing:.12em; text-transform:uppercase; color:var(--ink-3); flex:none; }}
.zlist {{ list-style:none; margin:0; padding:0; display:flex; flex-wrap:wrap; gap:7px; }}
.zlist li {{ display:inline-flex; align-items:center; gap:5px; padding:3px 8px;
  border:1px solid var(--line); border-radius:2px; font-size:12.5px; }}
.zh {{ font-weight:600; }}
.zn {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11px;
  color:var(--loss); font-weight:700; }}
.barcell {{ width:34%; min-width:110px; }}
.bar {{ display:flex; height:9px; background:var(--line-2); border-radius:2px; overflow:hidden; }}
.seg {{ display:block; height:100%; }}
.seg.p {{ background:var(--t0); }}
.seg.b {{ background:var(--loss-sq); }}
.idx tbody th {{ white-space:normal; }}
.none {{ margin:14px 0 0; font-size:13px; color:var(--ink-3); font-style:italic; }}
.legend {{ display:flex; flex-wrap:wrap; gap:16px; align-items:center; margin-top:30px;
  padding-top:16px; border-top:1px solid var(--line); font-size:12px; color:var(--ink-2); }}
.legend .k {{ display:inline-flex; align-items:center; gap:6px; }}
footer {{ margin-top:14px; font-size:11.5px; color:var(--ink-3); line-height:1.7;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
</style>
<div class="wrap">
<header class="top">
 <p class="eyebrow">{args.eyebrow}</p>
 <h1>{esc(args.title)}</h1>
 <p class="lede">{lede}</p>
</header>
<div class="strip">{strip}</div>
{''.join(body)}
<div class="legend">
 <span class="k"><span class="sqs"><i class="sq w"></i><i class="sq w"></i><i class="sq l"></i></span> form, oldest first</span>
 <span class="k">N &middot; games drafted</span>
 <span class="k">GPM &middot; gold per minute, averaged</span>
 <span class="k">IMP &middot; Stratz impact, benchmarked vs all players</span>
</div>
<footer>Source: Stratz GraphQL, leagueId 19719 &middot; {cov['tournament_games']} tournament games, {cov['from']}&ndash;{cov['to']}{('<br>' + args.note) if args.note else ''}</footer>
</div>
"""
Path(args.out).write_text(page)
print(f"wrote {args.out} ({len(page)} bytes)")
