#!/usr/bin/env python3
"""
bus_display.py
--------------
The main program for the Kilbirnie bus display.

WHAT IT DOES (the big picture):
  Every 30 seconds it asks Metlink "what's departing from our three stops?",
  works out how many minutes away each bus is, and writes a good-looking
  web page called display.html. A browser left open on that page (in
  full-screen "kiosk" mode) keeps reloading it, so the screen always shows
  fresh times. The Pi does the talking to Metlink; the browser just shows
  the result. That keeps your secret API key on the Pi and out of the screen.

HOW TO RUN:
  1. export METLINK_API_KEY="your-key-here"
  2. python3 bus_display.py
  3. Open display.html in a browser (full screen). It refreshes itself.

  To make it run forever, leave this script running - it loops on its own.
"""

import os
import sys
import time
import datetime
import urllib.request
import urllib.error
import json
import html

# --- Settings you can tweak ----------------------------------------------

PREDICTIONS_URL = "https://api.opendata.metlink.org.nz/v1/stop-predictions"

# Our three Kilbirnie stops. The label is just for our own display.
STOPS = {
    "6224": "Kilbirnie - Stop A",
    "7224": "Kilbirnie - Stop B",
    "7026": "Kilbirnie - Stop C",
}

REFRESH_SECONDS = 30                  # how often to fetch new data
SAFETY_MAX_ROWS = 30                  # absolute ceiling per stop (a guard only)
OUTPUT_FILE = "display.html"          # the page the screen will show
EXCLUDE_ROUTES = {"742"}              # routes to hide (742 is a school bus)

# Official Metlink route colours, copied from the live stop pages. Two badge
# styles: "fill" = solid coloured circle with white number; "outline" = coloured
# ring + number on the black background. Any route not listed falls back to
# school blue. (742 is excluded separately as a school bus.)
ROUTE_COLORS = {
    "2":   ("fill", "#005EB8", "#FFFFFF"),   # blue
    "3":   ("fill", "#5E9732", "#FFFFFF"),   # green
    "4":   ("fill", "#BF5403", "#FFFFFF"),   # orange
    "AX":  ("fill", "#8DC8E8", "#FFFFFF"),   # light blue (Airport Express)
    "14":  ("outline", "#308AD9"),           # blue ring
    "18":  ("outline", "#308AD9"),           # blue ring
    "24":  ("outline", "#308AD9"),           # blue ring
    "36":  ("outline", "#636466"),           # grey ring
    "38x": ("outline", "#636466"),           # grey ring
}

API_KEY = os.environ.get("METLINK_API_KEY")


# --- Talking to Metlink ---------------------------------------------------

def get_departures(stop_id):
    """Fetch departures for one stop. Returns a list (empty on any problem)."""
    url = f"{PREDICTIONS_URL}?stop_id={stop_id}"
    request = urllib.request.Request(url, headers={
        "x-api-key": API_KEY,
        "accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("departures", [])
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as e:
        # If one stop fails we don't want the whole board to crash -
        # just log it and carry on with the others.
        print(f"  Warning: could not fetch stop {stop_id}: {e}")
        return []


def minutes_until(timestamp):
    """Turn an ISO time like '2026-05-20T14:32:00+12:00' into minutes from now.
    Returns None if we can't read the time."""
    if not timestamp:
        return None
    try:
        # Python's parser handles the +12:00 timezone; tidy a trailing 'Z'.
        when = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        now = datetime.datetime.now(when.tzinfo)
        diff = (when - now).total_seconds() / 60
        return max(0, round(diff))
    except (ValueError, TypeError):
        return None


def collect_by_stop():
    """Fetch each stop separately. Returns a list of (stop_label, rows), in
    Stop A, B, C order, each list sorted soonest-first and capped per stop."""
    groups = []
    for stop_id, label in STOPS.items():
        rows = []
        for dep in get_departures(stop_id):
            route = str(dep.get("service_id", "?"))
            if route in EXCLUDE_ROUTES:        # e.g. 742 is a school bus - skip it
                continue
            times = dep.get("departure", {})
            mins = minutes_until(times.get("expected") or times.get("aimed"))
            rows.append({
                "route": route,
                "destination": dep.get("destination", {}).get("name", "Unknown"),
                "mins": mins,
                # "expected" present means it's a live, real-time prediction.
                "live": bool(times.get("expected")),
            })
        # Sort soonest-first; buses with no readable time go to the end.
        rows.sort(key=lambda r: (r["mins"] is None, r["mins"] if r["mins"] is not None else 9999))
        groups.append((label, trim_to_first_of_each(rows)))
    return groups


def trim_to_first_of_each(rows):
    """Keep the soonest departures and extend the list down just far enough that
    every route+destination serving this stop shows up at least once. (rows is
    already sorted soonest-first.) We key on route AND destination, so both
    directions of a route count separately - e.g. a No. 2 to Miramar and a No. 2
    to Seatoun both appear, and a No. 3 to Rongotai and a No. 3 to Lyall Bay both
    appear. Frequent variants may still repeat above the cut-off; that's fine."""
    key = lambda r: (r["route"], r["destination"])
    needed = {key(r) for r in rows}          # all route+destination variants here
    seen, out = set(), []
    for r in rows:
        out.append(r)
        seen.add(key(r))
        if seen >= needed:                   # every variant now appears at least once
            break
    return out[:SAFETY_MAX_ROWS]


# --- Building the screen --------------------------------------------------

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<!-- Tells phones/tablets to use their real screen width instead of pretending
     to be a ~980px desktop. Without this the mobile layout never kicks in. -->
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- This line tells the browser to reload the page automatically. -->
<meta http-equiv="refresh" content="{refresh}">
<!-- Montserrat is the school's heading font (loaded from Google Fonts).
     If the Pi is ever offline, the browser falls back to a system sans-serif. -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&display=swap" rel="stylesheet">
<title>Kilbirnie Bus Departures</title>
<style>
  /* clamp(MIN, FLUID, MAX) keeps text readable on a phone yet not silly-big
     on a 4K monitor: it scales with the screen but is capped at both ends. */
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  :root {{ --pad-x: clamp(14px, 4vw, 64px); }}
  html, body {{ height: 100%; }}
  body {{
    background: #000000;
    color: #e8eefc;
    font-family: "Montserrat", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    min-height: 100vh;
    display: flex; flex-direction: column;   /* header / board / footer stack */
  }}
  header {{
    display: flex; justify-content: space-between; align-items: baseline;
    flex-wrap: wrap; gap: 0.4em;              /* wraps instead of overflowing */
    padding: clamp(10px, 3vh, 32px) var(--pad-x) clamp(6px, 2vh, 20px);
    border-bottom: 3px solid #69AAE2;
  }}
  h1 {{ font-size: clamp(20px, 4.2vh, 46px); letter-spacing: 2px; color: #69AAE2; }}
  .clock {{ font-size: clamp(15px, 3.4vh, 34px); color: #7FA8C9; }}
  /* Three side-by-side stop panels on wide screens; they stack on narrow ones. */
  .board {{
    flex: 1; overflow: auto;
    display: grid; grid-template-columns: repeat(3, 1fr);
    gap: clamp(12px, 2vw, 30px);
    padding: clamp(10px, 2vh, 22px) var(--pad-x);
    align-content: start;
  }}
  .stoppanel {{ min-width: 0; }}
  .stopname {{
    color: #69AAE2; font-size: clamp(15px, 2.6vh, 24px);
    letter-spacing: 1px; padding-bottom: 0.3em; margin-bottom: 0.2em;
    border-bottom: 2px solid #14283b;
  }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{
    text-align: left; font-size: clamp(10px, 1.6vh, 15px); color: #5e83a3;
    text-transform: uppercase; letter-spacing: 1px;
    padding: 0.5em clamp(6px, 0.8vw, 14px); border-bottom: 1px solid #14283b;
  }}
  td {{
    padding: clamp(7px, 1.4vh, 14px) clamp(6px, 0.8vw, 14px);
    font-size: clamp(15px, 2.4vh, 30px); border-bottom: 1px solid #14283b;
    vertical-align: middle;
  }}
  .route {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 2.2em; height: 2.2em; box-sizing: border-box; padding: 0.1em;
    background: #69AAE2; color: #000000; font-weight: bold;
    border-radius: 50%;            /* makes each route number a circle */
    font-size: 0.82em; line-height: 1;
  }}
  .dest {{ color: #e8eefc; }}
  .mins {{ text-align: right; font-weight: bold; color: #9FD4FF; white-space: nowrap; }}
  .live::after {{
    content: "*"; color: #9FD4FF; margin-left: 0.3em; font-size: 0.6em;
    vertical-align: super;
  }}
  footer {{
    padding: clamp(8px, 1.4vh, 16px) var(--pad-x);
    font-size: clamp(10px, 1.8vh, 17px); color: #5e83a3;
    border-top: 1px solid #14283b;
  }}
  /* Tablets and phones: stack the three stop panels into a single column. */
  @media (max-width: 900px) {{
    .board {{ grid-template-columns: 1fr; }}
  }}
  @media (max-width: 600px) {{
    header {{ flex-direction: column; align-items: flex-start; }}
    .route {{ width: 2em; height: 2em; }}
  }}
  /* iPhone (and similar) in portrait, ~375-430px wide. The fluid sizes above
     key off screen HEIGHT, and a phone in portrait is very tall, so text would
     balloon. Here we pin fixed, sensible sizes and trim spacing so the three
     columns fit with no sideways scrolling, and long names wrap cleanly. */
  @media (max-width: 430px) {{
    :root {{ --pad-x: 12px; }}
    h1 {{ font-size: 21px; letter-spacing: 1px; }}
    .clock {{ font-size: 15px; }}
    th {{ font-size: 10px; }}
    td {{ font-size: 18px; }}
    .route {{ width: 1.9em; height: 1.9em; }}
    .dest {{ word-break: break-word; }}
    .mins {{ font-size: 18px; }}
  }}
</style>
</head>
<body>
  <header>
    <h1>KILBIRNIE METLINK BUS DEPARTURES</h1>
    <div class="clock">{clock}</div>
  </header>
  <div class="board">
    {panels}
  </div>
  <footer>* = live (real-time) &nbsp;&middot;&nbsp; Updated {clock} &nbsp;&middot;&nbsp; Data: Metlink / Greater Wellington Regional Council (CC BY 4.0)</footer>
</body>
</html>
"""

PANEL_TEMPLATE = (
    '<section class="stoppanel">'
    '<h2 class="stopname">{stop}</h2>'
    '<table><thead><tr>'
    '<th>Route</th><th>Destination</th><th style="text-align:right">Min</th>'
    '</tr></thead><tbody>{rows}</tbody></table>'
    '</section>'
)

ROW_TEMPLATE = (
    '<tr><td>{badge}</td>'
    '<td class="dest">{dest}</td>'
    '<td class="mins{live_class}">{mins}</td></tr>'
)


def route_badge(route):
    """Return the coloured circle for a route, using Metlink's own colours."""
    spec = ROUTE_COLORS.get(route)
    if spec and spec[0] == "fill":
        style = f"background:{spec[1]};color:{spec[2]};border:none"
    elif spec and spec[0] == "outline":
        style = f"background:transparent;color:{spec[1]};border:0.13em solid {spec[1]}"
    else:
        style = "background:#69AAE2;color:#000000;border:none"   # fallback: school blue
    return f'<span class="route" style="{style}">{html.escape(route)}</span>'


def build_panel(label, rows):
    """Build one stop's heading + 3-column table."""
    if rows:
        body = "".join(
            ROW_TEMPLATE.format(
                badge=route_badge(r["route"]),
                dest=html.escape(r["destination"]),
                mins=("Due" if r["mins"] == 0 else r["mins"]) if r["mins"] is not None else "--",
                live_class=" live" if r["live"] else "",
            )
            for r in rows
        )
    else:
        body = '<tr><td colspan="3" style="padding:2em 0.5em;color:#5e83a3">No departures right now.</td></tr>'
    return PANEL_TEMPLATE.format(stop=html.escape(label), rows=body)


def build_page(groups):
    clock = datetime.datetime.now().strftime("%H:%M:%S")
    panels = "\n".join(build_panel(label, rows) for label, rows in groups)
    return PAGE_TEMPLATE.format(refresh=REFRESH_SECONDS, clock=clock, panels=panels)


# --- Main loop ------------------------------------------------------------

def main():
    if not API_KEY:
        print("ERROR: No API key found.")
        print('Set it first with:  export METLINK_API_KEY="your-key-here"')
        sys.exit(1)

    print(f"Bus display running. Writing {OUTPUT_FILE} every {REFRESH_SECONDS}s.")
    print("Open that file in a full-screen browser. Press Ctrl+C to stop.\n")

    while True:
        groups = collect_by_stop()
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(build_page(groups))
        total = sum(len(rows) for _, rows in groups)
        print(f"  {datetime.datetime.now():%H:%M:%S}  wrote {total} departures across {len(groups)} stops")
        time.sleep(REFRESH_SECONDS)


if __name__ == "__main__":
    main()
