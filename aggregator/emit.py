"""Emit a unified events.ics (iCalendar) and feed.xml (RSS 2.0).

A "big names only" variant of each is also written, since first-class
attention to watchlisted orgs/people is a core goal.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

from icalendar import Alarm, Calendar
from icalendar import Event as IcsEvent

from .config import SOURCES
from .models import Event
from .provenance import marker, notes
from .remote import is_remote, safe_watch_url

PRODID = "-//dc-frontier-events//EN"
_LAYER = {s.slug: s.layer for s in SOURCES}
_NAME = {s.slug: s.name for s in SOURCES}

# Default subscribable-calendar name (overridable per feed). Google Calendar's
# "From URL" subscription reads X-WR-CALNAME as the calendar's display name and
# honors REFRESH-INTERVAL / X-PUBLISHED-TTL as a polling hint.
DEFAULT_CAL_NAME = "DC AI & Frontier Tech Events"
REFRESH_HINT = "PT12H"   # ask clients to re-poll twice a day


def _h(s: str) -> str:
    """Escape for HTML text and double-quoted attribute values."""
    return escape(s or "", {'"': "&quot;"})


def _safe_url(u: str | None) -> str:
    """Only http(s) URLs may become links / popup hrefs, blocking javascript:,
    data:, and other script-bearing schemes from scraped source_urls."""
    u = (u or "").strip()
    lo = u.lower()
    return u if lo.startswith("http://") or lo.startswith("https://") else ""


def _parse_dt(iso: str | None):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        try:
            return date.fromisoformat(iso[:10])
        except ValueError:
            return None


def filter_upcoming(events: list[Event], today_iso: str) -> list[Event]:
    """Events whose start date is today or later. ISO date strings compare
    chronologically as plain strings, so this works on both date and datetime starts."""
    return [e for e in events if (e.start or "")[:10] >= today_iso]


def _to_utc(dt):
    """Normalize an aware datetime to UTC so iCal emits an unambiguous '...Z'.
    icalendar serializes a fixed-offset tz as an invalid TZID (e.g. "UTC-04:00")
    with no VTIMEZONE; converting to UTC avoids that. Naive/date values pass through.
    """
    if isinstance(dt, datetime) and dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    return dt


def _star(ev: Event) -> str:
    return "★ " if ev.is_big_name else ""


def build_ics(events: list[Event], today_iso: str | None = None,
              cal_name: str = DEFAULT_CAL_NAME) -> tuple[bytes, int]:
    cal = Calendar()
    cal.add("prodid", PRODID)
    cal.add("version", "2.0")
    # Subscription metadata so the file works as a live calendar feed (Google
    # Calendar "From URL", Apple Calendar, Outlook). NAME differs per feed so a
    # subscriber can tell the upcoming / big-names / archive calendars apart.
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", cal_name)
    cal.add("name", cal_name)  # RFC 7986 NAME (newer clients)
    cal.add("x-wr-caldesc", "Aggregated, deduped, ranked DC-metro AI, semiconductor "
                            "& frontier-tech events. github.com/.../dc-frontier-events")
    cal.add("x-wr-timezone", "UTC")
    cal.add("refresh-interval;value=duration", REFRESH_HINT)
    cal.add("x-published-ttl", REFRESH_HINT)
    now = datetime.now(timezone.utc)
    n = 0
    for ev in events:
        dt = _parse_dt(ev.start)
        if dt is None:
            continue
        ie = IcsEvent()
        ie.add("uid", ev.id)
        ie.add("dtstamp", now)
        ie.add("summary", _star(ev) + ev.title)
        ie.add("dtstart", _to_utc(dt))
        end = _parse_dt(ev.end)
        if end is not None:
            ie.add("dtend", _to_utc(end))
        if ev.address:
            ie.add("location", ev.address + (" (approx · host venue)" if marker(ev) else ""))
        if ev.lat is not None and ev.lng is not None:
            ie.add("geo", (ev.lat, ev.lng))
        if ev.topics:
            ie.add("categories", ev.topics)
        # RFC 7986 COLOR: red=big-name, purple=L2 policy, green=L3 univ, blue=L1.
        color = ("red" if ev.is_big_name
                 else {2: "purple", 3: "green"}.get(_LAYER.get(ev.source, 1), "blue"))
        ie.add("color", color)
        desc = ev.description
        surl = _safe_url(ev.source_url)
        if surl:
            ie.add("url", surl)
            desc = f"{desc}\n\nSource: {surl}".strip()
        prov_notes = notes(ev)
        if prov_notes:
            desc = f"{desc}\n\nNotes: {'; '.join(prov_notes)}".strip()
        if is_remote(ev):
            w = safe_watch_url(ev)
            desc = f"{desc}\n\nRemote viewing available{': ' + w if w else ''}".strip()
        ie.add("description", desc)
        # A 1-day-before reminder, only for upcoming events.
        if today_iso and (ev.start or "")[:10] >= today_iso:
            alarm = Alarm()
            alarm.add("action", "DISPLAY")
            alarm.add("description", ev.title)
            alarm.add("trigger", timedelta(days=-1))
            ie.add_component(alarm)
        cal.add_component(ie)
        n += 1
    return cal.to_ical(), n


def render_ics(events: list[Event], today_iso: str | None = None,
               cal_name: str = DEFAULT_CAL_NAME) -> bytes:
    data, _ = build_ics(events, today_iso, cal_name)
    return data


def write_ics(events: list[Event], path: str, today_iso: str | None = None,
              cal_name: str = DEFAULT_CAL_NAME) -> int:
    data, n = build_ics(events, today_iso, cal_name)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return n


def _rfc822(iso: str | None) -> str:
    dt = _parse_dt(iso)
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    elif isinstance(dt, date):
        dt = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    else:
        dt = datetime.now(timezone.utc)
    return format_datetime(dt)


def write_rss(events: list[Event], path: str,
              title: str = "DC AI & Frontier Tech Events") -> int:
    items = []
    for ev in events:
        topics = ", ".join(ev.topics)
        big = "★ MARQUEE -- " if ev.is_big_name else ""
        body = "\n".join(p for p in [ev.address, ev.description,
                                     f"Topics: {topics}" if topics else ""] if p)
        items.append(
            "<item>"
            f"<title>{escape(_star(ev) + ev.title)}</title>"
            f"<link>{escape(_safe_url(ev.source_url))}</link>"
            f'<guid isPermaLink="false">{escape(ev.id)}</guid>'
            f"<pubDate>{_rfc822(ev.start)}</pubDate>"
            f"<description>{escape(big + body)}</description>"
            "</item>"
        )
    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        f"<title>{escape(title)}</title>"
        "<link>https://lu.ma/DC2</link>"
        f"<description>{escape(title)} -- aggregated, deduped, filtered.</description>"
        + "".join(items)
        + "</channel></rss>"
    )
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(rss)
    return len(items)


def _event_dicts(events: list[Event]) -> list[dict]:
    out = []
    for ev in events:
        d = asdict(ev)
        d["layer"] = _LAYER.get(ev.source, 0)
        d["score"] = ev.raw.get("score")
        d["remote"] = is_remote(ev)
        d["watch_url"] = safe_watch_url(ev)
        # asdict() copied the whole raw -- overwrite the raw copy's watch_url with
        # the sanitized value so no scraped javascript:/data: URL leaks via raw.
        if isinstance(d.get("raw"), dict) and "watch_url" in d["raw"]:
            d["raw"]["watch_url"] = safe_watch_url(ev)
        out.append(d)
    return out


def write_json(events: list[Event], path: str) -> int:
    """Machine-readable export of the full normalized event set."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_event_dicts(events), f, ensure_ascii=False, indent=2, default=str)
    return len(events)


# Interactive map: server-rendered sidebar list (one <li> per event, with data-
# attributes) + a Leaflet/MarkerCluster map. JS builds markers from the list and
# filters both list and markers by layer / big-name / upcoming / search. No
# str.format here, so JS braces stay literal; only the <li> block is injected.
_MAP_HEAD = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#000000">
<link rel="canonical" href="https://events.emersus.ai/map.html">
<title>DC AI & Frontier Tech Events · Map</title>
<meta name="description" content="Interactive map of upcoming AI, semiconductor and frontier-tech events across the Washington DC metro.">

<link rel="preconnect" href="https://unpkg.com" crossorigin>
<link rel="preconnect" href="https://a.basemaps.cartocdn.com">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<style>
*{box-sizing:border-box}
:root{--ink:#f5f5f7;--muted:#86868b;--muted2:#a1a1a6;--accent:#2997ff;--bg:#000;--card:#1d1d1f;--line:#424245}
body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px;
background:var(--bg);color:var(--ink)}
.topbar{display:flex;align-items:center;gap:12px;height:52px;padding:0 16px;
background:rgba(0,0,0,.72);-webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);
border-bottom:1px solid var(--line);color:#f5f5f7}
.topbar a{color:#f5f5f7;text-decoration:none}
.topbar .home{font-weight:700;font-size:15px;letter-spacing:-.01em}
.topbar .spacer{flex:1}
.topbar .nav{font-size:13px;background:var(--card);border:1px solid var(--line);
padding:6px 14px;border-radius:980px}
.topbar .nav:hover{border-color:#5a5a5e}
#app{display:flex;height:calc(100vh - 52px)}
#sidebar{width:360px;min-width:300px;display:flex;flex-direction:column;border-right:1px solid var(--line);
background:var(--bg)}
#controls{padding:12px;border-bottom:1px solid var(--line)}
#controls input[type=text]{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:12px;
font-size:14px;margin-bottom:8px;background:var(--card);color:var(--ink)}
#controls input[type=text]::placeholder{color:var(--muted)}
#controls label{display:inline-block;margin-right:10px;font-size:12px;white-space:nowrap;cursor:pointer}
#count{margin-top:8px;color:var(--muted);font-size:12px}
#list{flex:1;overflow:auto;margin:0;padding:0;list-style:none}
#list li{padding:10px 12px;border-bottom:1px solid #2c2c2e;cursor:pointer}
#list li:hover{background:var(--card)}
#list li small{color:var(--muted2)}
#map{flex:1;background:#000}
.star{color:#ff453a}
.evname{color:var(--accent);text-decoration:none;font-weight:650}
#list li:hover .evname{text-decoration:underline}
.lg{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:3px;vertical-align:middle}
.badge{border-radius:980px;padding:0 8px;font-size:10.5px;font-weight:700;margin-left:5px}
.b-virtual{background:rgba(41,151,255,.16);color:#6db4ff}.b-person{background:rgba(48,209,88,.16);color:#30d158}
.leaflet-popup-content-wrapper,.leaflet-popup-tip{background:#1d1d1f;color:#f5f5f7;
box-shadow:0 2px 14px rgba(0,0,0,.6)}
.leaflet-popup-content a{color:#2997ff}
.leaflet-container .leaflet-control-attribution{background:rgba(0,0,0,.6);color:#86868b}
.leaflet-control-attribution a{color:#a1a1a6}
</style></head>
<body>
<header class="topbar"><a class="home" href="index.html">← DC AI &amp; Frontier Tech</a>
<span class="spacer"></span><a class="nav" href="index.html">☰ List view</a>
<a class="nav" href="events-upcoming.ics">📅 Subscribe</a></header>
<main id="app"><div id="sidebar"><div id="controls">
<input type="text" id="search" placeholder="Search events…">
<div>
<label><input type="checkbox" class="flt-layer" value="1" checked><span class="lg" style="background:#2997ff"></span>L1</label>
<label><input type="checkbox" class="flt-layer" value="2" checked><span class="lg" style="background:#bf5af2"></span>L2</label>
<label><input type="checkbox" class="flt-layer" value="3" checked><span class="lg" style="background:#30d158"></span>L3</label>
</div><div>
<label><input type="checkbox" id="flt-big"><span class="lg" style="background:#ff453a"></span>Marquee</label>
</div><div id="count"></div></div>
<ul id="list">
"""

_MAP_TAIL = """</ul></div><div id="map"></div></main>
<script>
var map=L.map('map').setView([38.9,-77.03],11);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{maxZoom:19,attribution:'© OpenStreetMap contributors © CARTO'}).addTo(map);
var cluster=L.markerClusterGroup();map.addLayer(cluster);
var lis=[].slice.call(document.querySelectorAll('#list li.ev'));
lis.forEach(function(li){
  var lat=parseFloat(li.getAttribute('data-lat')),lng=parseFloat(li.getAttribute('data-lng'));
  if(!isNaN(lat)&&!isNaN(lng)){
    var ly=li.getAttribute('data-layer');
    var color=li.getAttribute('data-big')==='1'?'#ff453a':(ly==='2'?'#bf5af2':(ly==='3'?'#30d158':'#2997ff'));
    var m=L.circleMarker([lat,lng],{radius:7,color:color,fillColor:color,fillOpacity:.85,weight:1});
    var url=li.getAttribute('data-url');
    var nm=li.querySelector('.evname').textContent;
    // Build the popup with DOM nodes (textContent / setAttribute), never innerHTML
    // string concatenation, so event titles/urls can't inject HTML or script.
    var pop=document.createElement('div');
    var head=document.createElement(url?'a':'b');
    if(url){head.setAttribute('href',url);head.setAttribute('target','_blank');head.setAttribute('rel','noopener');var hb=document.createElement('b');hb.textContent=nm;head.appendChild(hb);}else{head.textContent=nm;}
    pop.appendChild(head);
    pop.appendChild(document.createElement('br'));
    pop.appendChild(document.createTextNode(li.getAttribute('data-date')||''));
    if(url){pop.appendChild(document.createElement('br'));var more=document.createElement('a');more.setAttribute('href',url);more.setAttribute('target','_blank');more.setAttribute('rel','noopener');more.textContent='Event page →';pop.appendChild(more);}
    m.bindPopup(pop);
    li._m=m;
  }
  // Clicking the event NAME opens its page; don't also fly the map.
  var a=li.querySelector('a.evname');
  if(a){a.addEventListener('click',function(e){e.stopPropagation();});}
  li.addEventListener('click',function(){if(li._m){map.setView(li._m.getLatLng(),14);cluster.zoomToShowLayer(li._m,function(){li._m.openPopup();});}});
});
function render(){
  var q=document.getElementById('search').value.toLowerCase().trim();
  var layers=[].slice.call(document.querySelectorAll('.flt-layer:checked')).map(function(c){return c.value;});
  var big=document.getElementById('flt-big').checked;
  cluster.clearLayers();var shown=0;
  lis.forEach(function(li){
    var ok=layers.indexOf(li.getAttribute('data-layer'))>=0
      &&(!big||li.getAttribute('data-big')==='1')
      &&(!q||li.getAttribute('data-text').indexOf(q)>=0);
    li.style.display=ok?'':'none';
    if(ok){shown++;if(li._m)cluster.addLayer(li._m);}
  });
  document.getElementById('count').textContent=shown+' of '+lis.length+' events';
}
document.getElementById('search').addEventListener('input',render);
[].slice.call(document.querySelectorAll('.flt-layer,#flt-big')).forEach(function(c){c.addEventListener('change',render);});
render();
</script><script src="/analytics.js" defer></script></body></html>
"""


def _li(ev: Event) -> str:
    layer = _LAYER.get(ev.source, 0)
    topics = ", ".join(t for t in ev.topics if not t.startswith("big:"))
    src = _NAME.get(ev.source, ev.source)
    date = (ev.start or "")[:10]
    score = ev.raw.get("score")
    text = " ".join([ev.title, src, topics, ev.address or ""]).lower()
    coords = (f' data-lat="{ev.lat}" data-lng="{ev.lng}"'
              if ev.lat is not None and ev.lng is not None else "")
    star = '<span class="star">★</span> ' if ev.is_big_name else ""
    meta = f"{date} · {_h(src)} · {_h(topics) or '-'}"
    if marker(ev):
        meta += f" · {marker(ev)}"
    if score is not None:
        meta += f" · ●{score}"
    virtual = bool(ev.raw.get("virtual")) and not ev.address
    badge = ('<span class="badge b-virtual">virtual</span>' if virtual
             else '<span class="badge b-person">in&#8209;person</span>' if ev.address else "")
    # The event name links to its source/detail page (new tab). Falls back to
    # bold text when an event has no source_url.
    name = _h(ev.title)
    surl = _safe_url(ev.source_url)   # http(s) only -> no javascript:/data: links
    title_html = (f'<a class="evname" href="{_h(surl)}" target="_blank" '
                  f'rel="noopener">{name}</a>' if surl
                  else f'<b class="evname">{name}</b>')
    return (f'<li class="ev" data-layer="{layer}" data-big="{1 if ev.is_big_name else 0}"'
            f' data-date="{date}"'
            f' data-url="{_h(surl)}" data-text="{_h(text)}"{coords}>'
            f'{star}{title_html}{badge}<br><small>{meta}</small></li>')


def write_map(events: list[Event], path: str, today_iso: str) -> int:
    """Self-contained interactive map: filterable, searchable sidebar list synced
    to a clustered Leaflet map. Only upcoming events (start >= today) are shown.
    Returns the number of upcoming events with GEO (map pins)."""
    upcoming = filter_upcoming(events, today_iso)
    geo = [e for e in upcoming if e.lat is not None and e.lng is not None]
    items = sorted(upcoming, key=lambda e: (-(e.raw.get("score") or 0), e.start or ""))
    lis = "\n".join(_li(e) for e in items)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(_MAP_HEAD + lis + _MAP_TAIL)
    return len(geo)
