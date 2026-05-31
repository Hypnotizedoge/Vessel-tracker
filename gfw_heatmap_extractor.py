"""
===============================================================================
  GFW Daily Vessel Activity Extractor (API-Optimized)
===============================================================================

  Extracts daily activity data for each vessel in your vessels.xlsx.
  Outputs a clean CSV showing: date, vessel, activity, location, duration.

  API CALLS:  1 (resolve) + 1 (events) = 2 per vessel
  UPLOAD TO COLAB:  this file + vessels.xlsx
  RUN:  %run gfw_heatmap_extractor.py

===============================================================================
"""

import requests
import pandas as pd
import os
import time
from datetime import datetime, timedelta

# ═════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION — edit these before running
# ═════════════════════════════════════════════════════════════════════════════

GFW_API_TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6ImtpZEtleSJ9.eyJkYXRhIjp7Im5hbWUiOiJTaGlwIHRyYWNrZXIiLCJ1c2VySWQiOjYzMDEwLCJhcHBsaWNhdGlvbk5hbWUiOiJTaGlwIHRyYWNrZXIiLCJpZCI6MTExMDMsInR5cGUiOiJ1c2VyLWFwcGxpY2F0aW9uIn0sImlhdCI6MTc3OTk1MzQ2NywiZXhwIjoyMDk1MzEzNDY3LCJhdWQiOiJnZnciLCJpc3MiOiJnZncifQ.Fd7dONE_4LfCx_8PeA8ENGC3_1Yfy8qOE4gLXJxJXbtLLBNYoi7E00foeXGWP6RjMZqXzJtul1JtbRIc-qyG3A8i65wlohUz7wvLOcivqpKZTEdr_cGw3lArre1ATTR7jPgmrcsOWju9qj415tseujQ8fCep4If-3cyIWDvMtpSpUd9IPVvtKwow_2airBYYRN3seU7SIQSrktAwuxG3Kc8TPoSEpzvjaQYhYeqMOCrdXvrPA0-qrtzeHDBWsXty03-mYZJgNXCvlHR9wY21J3Y5m_uPqlO5R7iXs1qxASlB51mz5ePkm0Qs7YFGocdccoiNiK1iRCSuIyAHSIWAuG5dQvxvBO8fmXRumgXZaVD3lrSsi2donFCZbNZxq0Jixh2Lug6FkV3u3S0Tue5y3-HlC4LcPobH7R6jMWGXV4RElGRf-R7kEN5pPz36EGwrIaxOjgPDthBsUoNi0DEimyiblcbdbIisYOiRqL26Df2V-H29Q0idmjil1trZKdUx"

GFW_API_BASE = "https://gateway.api.globalfishingwatch.org/v3"
HEADERS = {
    "Authorization": f"Bearer {GFW_API_TOKEN}",
    "Content-Type": "application/json",
}

# Date range — last 3 months
END_DATE = datetime.utcnow().date()
START_DATE = END_DATE - timedelta(days=90)

# Output file path (Colab path)
OUTPUT_FILE = "/content/gfw_extracted_data.csv"

# ─── EVENT TYPES TO FETCH ────────────────────────────────────────────────────
# Each entry = 1 extra API call per vessel.
# Comment out any you DON'T need to save API calls.
EVENT_DATASETS = {
    "fishing":    "public-global-fishing-events:latest",
    "loitering":  "public-global-loitering-events:latest",
    "port_visit": "public-global-port-visits-events:latest",
    # "encounter":  "public-global-encounters-events:latest",   # uncomment if needed
    # "gap":        "public-global-gaps-events:latest",          # uncomment if needed
}

IDENTITY_DATASET = "public-global-vessel-identity:latest"


# ═════════════════════════════════════════════════════════════════════════════
#  FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════

def load_vessels(filepath="/content/vessels.xlsx"):
    """Read vessel list from Excel. Returns list of {name, mmsi}."""
    df = pd.read_excel(filepath, sheet_name="Watchlist", dtype=str)
    df.columns = df.columns.str.strip().str.lower()
    vessels = []
    for _, row in df.iterrows():
        mmsi = str(row.get("mmsi", "")).strip()
        name = str(row.get("vessel name", "Unknown")).strip()
        if mmsi:
            vessels.append({"name": name, "mmsi": mmsi})
    return vessels


def make_request_with_retries(url: str, params: dict = None, timeout: int = 30, max_retries: int = 3) -> requests.Response | None:
    """
    Wrapper around requests.get with retries and exponential backoff to handle
    timeouts and temporary network/server issues.
    """
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
            # If server returns a temporary error or rate limit, retry
            if r.status_code in [429, 502, 503, 504]:
                print(f"\n   ⚠️  GFW API returned status {r.status_code}. Retrying in {attempt * 3}s... (Attempt {attempt}/{max_retries})")
                time.sleep(attempt * 3)
                continue
            return r
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            print(f"\n   ⚠️  Network timeout/connection error: {type(e).__name__}. Retrying in {attempt * 5}s... (Attempt {attempt}/{max_retries})")
            time.sleep(attempt * 5)
        except requests.exceptions.RequestException as e:
            print(f"\n   ❌ Request failed: {e}")
            return None
    print(f"\n   ❌ Failed to get response after {max_retries} attempts.")
    return None


def resolve_vessel(mmsi: str) -> dict | None:
    """
    MMSI → GFW vessel ID.  (1 API call)
    """
    r = make_request_with_retries(
        f"{GFW_API_BASE}/vessels/search",
        params={"query": mmsi, "limit": 5, "datasets[0]": IDENTITY_DATASET},
        timeout=20,
    )
    if not r or r.status_code != 200:
        return None

    entries = r.json().get("entries", [])
    if not entries:
        return None

    # Pick the entry with the most AIS messages
    best = max(
        entries,
        key=lambda e: (
            e.get("selfReportedInfo", [{}])[0].get("messagesCounter", 0)
            if e.get("selfReportedInfo") else 0
        ),
    )

    vessel_id = None
    if best.get("combinedSourcesInfo"):
        vessel_id = best["combinedSourcesInfo"][0].get("vesselId")
    if not vessel_id and best.get("selfReportedInfo"):
        vessel_id = best["selfReportedInfo"][0].get("id")
    if not vessel_id:
        return None

    info = best.get("selfReportedInfo", [{}])[0] if best.get("selfReportedInfo") else {}
    return {
        "id": vessel_id,
        "name": info.get("shipname", f"MMSI {mmsi}"),
        "flag": info.get("flag", "N/A"),
    }


def fetch_events(vessel_id: str, start: str, end: str) -> list[dict]:
    """
    Fetch all events for a vessel.  (1 API call per event type)
    Paginates automatically. Returns flat list of event dicts.
    """
    rows = []

    for event_type, dataset_id in EVENT_DATASETS.items():
        offset = 0
        while True:
            r = make_request_with_retries(
                f"{GFW_API_BASE}/events",
                params={
                    "vessels[0]": vessel_id,
                    "datasets[0]": dataset_id,
                    "start-date": start,
                    "end-date": end,
                    "limit": 99,
                    "offset": offset,
                },
                timeout=30,
            )
            if not r or r.status_code != 200:
                print(f"\n   ⚠️  Skipping remaining pages/entries for {event_type} due to request failure.")
                break

            resp = r.json()
            entries = resp.get("entries", [])
            if not entries:
                break

            for e in entries:
                # Extract position
                pos = e.get("position", {})
                lat = pos.get("lat")
                lon = pos.get("lon")
                if lat is None or lon is None:
                    bbox = e.get("boundingBox")
                    if bbox and len(bbox) == 4:
                        lon, lat = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
                if lat is None or lon is None:
                    continue

                # Calculate duration
                start_t = e.get("start", "")
                end_t = e.get("end", "")
                dur = 0.0
                if start_t and end_t:
                    try:
                        dt_s = datetime.fromisoformat(start_t.replace("Z", "+00:00"))
                        dt_e = datetime.fromisoformat(end_t.replace("Z", "+00:00"))
                        dur = round((dt_e - dt_s).total_seconds() / 3600, 2)
                    except Exception:
                        pass

                # Extract event-specific details
                detail = ""
                if event_type == "fishing":
                    f_info = e.get("fishing", {})
                    detail = f"speed:{f_info.get('averageSpeedKnots', 0):.1f}kt dist:{f_info.get('totalDistanceKm', 0):.1f}km"
                elif event_type == "port_visit":
                    p_info = e.get("portVisit", {})
                    detail = p_info.get("portName") or "Unknown Port"
                elif event_type == "loitering":
                    l_info = e.get("loitering", {})
                    detail = f"speed:{l_info.get('averageSpeedKnots', 0):.1f}kt"
                elif event_type == "encounter":
                    enc = e.get("encounter", {}).get("vessel", {})
                    detail = enc.get("name") or "Unknown"
                elif event_type == "gap":
                    detail = f"gap:{dur:.1f}hrs"

                rows.append({
                    "date": start_t[:10],
                    "activity": event_type,
                    "lat": round(float(lat), 4),
                    "lon": round(float(lon), 4),
                    "duration_hours": dur,
                    "start_time": start_t,
                    "end_time": end_t,
                    "detail": detail,
                })

            # Pagination
            total = resp.get("total", len(entries))
            offset += len(entries)
            if offset >= total:
                break

        time.sleep(0.3)  # rate limit between event types

    return rows


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main():
    # Make sure output directory exists
    out_dir = os.path.dirname(OUTPUT_FILE)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # ── Load vessels from Excel ───────────────────────────────────────────
    print("📂 Loading vessels from vessels.xlsx...")
    vessels = load_vessels()
    print(f"   Found {len(vessels)} vessel(s)\n")

    n_types = len(EVENT_DATASETS)
    total_calls = len(vessels) * (1 + n_types)
    print(f"📅 Date range    : {START_DATE} → {END_DATE} ({(END_DATE - START_DATE).days} days)")
    print(f"📊 Event types   : {', '.join(EVENT_DATASETS.keys())}")
    print(f"📡 API calls     : ~{total_calls} total  ({1} resolve + {n_types} events × {len(vessels)} vessels)")
    print("=" * 60)

    all_dfs = []

    for i, v in enumerate(vessels, 1):
        print(f"\n[{i}/{len(vessels)}] {v['name']} (MMSI: {v['mmsi']})")

        # Step 1: Resolve MMSI → GFW ID  (1 API call)
        print(f"   🔍 Resolving...", end=" ")
        vessel = resolve_vessel(v["mmsi"])
        if not vessel:
            print("❌ Not found — skipping")
            continue
        print(f"✅ {vessel['name']} ({vessel['flag']})")

        # Step 2: Fetch events  (N API calls, one per event type)
        print(f"   📡 Fetching events...", end=" ")
        events = fetch_events(vessel["id"], START_DATE.isoformat(), END_DATE.isoformat())

        if not events:
            print("⚠️  No events found")
            continue

        df = pd.DataFrame(events)
        df.insert(0, "vessel_name", v["name"])
        df.insert(1, "vessel_mmsi", v["mmsi"])
        df.insert(2, "vessel_flag", vessel["flag"])

        print(f"✅ {len(df)} events")

        all_dfs.append(df)
        time.sleep(0.5)  # rate limit between vessels

    # ── Save single combined output ───────────────────────────────────────
    if not all_dfs:
        print("\n❌ No data extracted for any vessel.")
        return

    combined = pd.concat(all_dfs, ignore_index=True)
    combined.sort_values(["date", "vessel_name"], inplace=True)

    # Save to the single output file
    combined.to_csv(OUTPUT_FILE, index=False)

    # Calculate daily summary for on-screen preview (but don't save to a file)
    summary = (
        combined.groupby(["date", "vessel_name", "vessel_mmsi"])
        .agg(
            activities=("activity", lambda x: ", ".join(sorted(set(x)))),
            event_count=("activity", "count"),
            total_hours=("duration_hours", "sum"),
            fishing_hours=("duration_hours", lambda x: x[combined.loc[x.index, "activity"] == "fishing"].sum()),
            avg_lat=("lat", "mean"),
            avg_lon=("lon", "mean"),
        )
        .reset_index()
    )
    summary["total_hours"] = summary["total_hours"].round(2)
    summary["fishing_hours"] = summary["fishing_hours"].round(2)
    summary["avg_lat"] = summary["avg_lat"].round(4)
    summary["avg_lon"] = summary["avg_lon"].round(4)

    # ── Print results ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("✅ DONE!")
    print("=" * 60)
    print(f"\n💾 Data saved to: {OUTPUT_FILE}")
    size = os.path.getsize(OUTPUT_FILE) / 1024
    print(f"   File size: {size:.1f} KB")

    print(f"\n📊 Daily summary preview:\n")
    print(summary.head(20).to_string(index=False))

    print(f"\n💡 Download the file from Colab's file browser (📁 left panel)")


if __name__ == "__main__":
    main()
