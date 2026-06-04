#!/usr/bin/env python3
"""
metlink_test.py
---------------
A tiny script to confirm your Metlink API key works.

What it does: asks Metlink "what's departing from one stop right now?"
and prints the answer in plain English. Run this FIRST, before the full
display, so you know the key and the connection are good.

HOW TO RUN (on the Pi or any computer with Python 3):

    1. Get your API key from https://opendata.metlink.org.nz (it's on your
       dashboard after you log in).
    2. Put the key in an environment variable so it never lives in the code:
           export METLINK_API_KEY="paste-your-key-here"
    3. Run the script:
           python3 metlink_test.py
"""

import os
import sys
import urllib.request
import urllib.error
import json

# --- Settings -------------------------------------------------------------

# The one endpoint we need: "what's departing from this stop?"
PREDICTIONS_URL = "https://api.opendata.metlink.org.nz/v1/stop-predictions"

# We'll test with Kilbirnie Stop A. Change this to 7224 or 7026 to try the others.
TEST_STOP_ID = "6224"

# Read the key from the environment so it stays out of the code (safer).
API_KEY = os.environ.get("METLINK_API_KEY")


def get_departures(stop_id):
    """Ask Metlink for departures from one stop. Returns the parsed JSON."""
    # The stop id goes on the end of the URL as a query parameter.
    url = f"{PREDICTIONS_URL}?stop_id={stop_id}"

    # The key travels in the request "headers" - like a sealed envelope label
    # that tells Metlink who's asking. "accept" says we'd like JSON back.
    request = urllib.request.Request(url, headers={
        "x-api-key": API_KEY,
        "accept": "application/json",
    })

    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw)


def main():
    if not API_KEY:
        print("ERROR: No API key found.")
        print('Set it first with:  export METLINK_API_KEY="your-key-here"')
        sys.exit(1)

    print(f"Asking Metlink about stop {TEST_STOP_ID}...\n")

    try:
        data = get_departures(TEST_STOP_ID)
    except urllib.error.HTTPError as e:
        # 403 usually means the key is wrong or not active yet.
        print(f"Metlink returned an error: HTTP {e.code} {e.reason}")
        if e.code == 403:
            print("A 403 usually means the API key is missing, wrong, or not active.")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Could not reach Metlink (network problem?): {e.reason}")
        sys.exit(1)

    # The list of upcoming buses lives under the "departures" key.
    departures = data.get("departures", [])

    if not departures:
        print("No departures returned right now (could be late at night).")
        return

    print(f"Next departures from stop {TEST_STOP_ID}:\n")
    for dep in departures[:10]:  # show up to 10
        route = dep.get("service_id", "?")             # e.g. "2", "24"
        destination = dep.get("destination", {}).get("name", "Unknown")
        times = dep.get("departure", {})
        # "expected" is the real-time prediction; "aimed" is the timetable time.
        when = times.get("expected") or times.get("aimed") or "?"
        print(f"  Route {route:<4} -> {destination:<30} at {when}")

    print("\nSuccess! Your key works. You're ready for the full display.")


if __name__ == "__main__":
    main()
