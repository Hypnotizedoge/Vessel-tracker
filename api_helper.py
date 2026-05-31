import requests
import logging
import json
import os
from datetime import datetime
import streamlit as st
import pandas as pd

from config import (
    GFW_API_TOKEN,
    GFW_API_BASE_URL,
    IDENTITY_DATASET,
    FISHING_DATASET,
    LOITERING_DATASET,
    ENCOUNTER_DATASET,
    PORT_VISIT_DATASET,
    GAP_DATASET,
)

logger = logging.getLogger(__name__)
headers = {
    "Authorization": f"Bearer {GFW_API_TOKEN}",
    "Content-Type": "application/json"
}

# ---------------------------------------------------------------------------
# Data persistence — save API responses to local files
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)


def save_vessel_data(
    vessel_name: str,
    mmsi: str,
    events: list[dict],
    start_date: str,
    end_date: str,
) -> tuple[str, str]:
    """
    Save fetched event data to CSV and JSON in the data/ directory.

    Returns (csv_path, json_path).
    """
    safe_name = (vessel_name or mmsi).replace(" ", "_").replace("/", "_")
    base = f"{safe_name}_{mmsi}_{start_date}_to_{end_date}"

    # ── CSV (without the bulky 'raw' blob) ────────────────────────────────
    csv_path = os.path.join(DATA_DIR, f"{base}_events.csv")
    clean_rows = [{k: v for k, v in e.items() if k != "raw"} for e in events]
    if clean_rows:
        pd.DataFrame(clean_rows).to_csv(csv_path, index=False)

    # ── JSON (full data for programmatic re-use) ──────────────────────────
    json_path = os.path.join(DATA_DIR, f"{base}_events.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(clean_rows, f, indent=2, default=str)

    logger.info("Data saved → %s  |  %s", csv_path, json_path)
    return csv_path, json_path

@st.cache_data(show_spinner="Searching vessels...")
def search_vessels(query: str) -> list[dict]:
    """
    Search for vessels by name, MMSI, IMO or callsign.
    Uses GFW Vessels API v3 search.
    """
    if not query or len(query.strip()) < 3:
        return []
    
    url = f"{GFW_API_BASE_URL}/vessels/search"
    params = {
        "query": query.strip(),
        "limit": 10,
        "datasets[0]": IDENTITY_DATASET
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code == 200:
            entries = r.json().get("entries", [])
            results = []
            for entry in entries:
                # Extract details
                vessel_id = None
                if entry.get("combinedSourcesInfo"):
                    vessel_id = entry["combinedSourcesInfo"][0].get("vesselId")
                if not vessel_id and entry.get("selfReportedInfo"):
                    vessel_id = entry["selfReportedInfo"][0].get("id")
                
                if not vessel_id:
                    continue
                
                info = entry.get("selfReportedInfo", [{}])[0]
                registry = entry.get("registryInfo", [{}])
                
                name = info.get("shipname") or (registry[0].get("shipname") if registry else "UNKNOWN")
                mmsi = info.get("ssvid") or (registry[0].get("ssvid") if registry else "N/A")
                flag = info.get("flag") or (registry[0].get("flag") if registry else "N/A")
                imo = info.get("imo") or (registry[0].get("imo") if registry else None)
                
                results.append({
                    "id": vessel_id,
                    "name": f"{name} (MMSI: {mmsi})",
                    "shipname": name,
                    "mmsi": mmsi,
                    "flag": flag,
                    "imo": imo,
                    "raw": entry
                })
            return results
        else:
            logger.error("Vessel search failed (Status %s): %s", r.status_code, r.text)
    except Exception as e:
        logger.error("Error in search_vessels: %s", e)
    return []


@st.cache_data(show_spinner="Resolving vessel from MMSI...")
def resolve_vessel_by_mmsi(mmsi: str, display_name: str = "") -> dict | None:
    """
    Look up a vessel by MMSI and return the best-matching identity.
    Picks the entry with the most AIS messages (= most active identity).

    Returns a dict with keys: id, name, mmsi, flag, type
    or None if not found.
    """
    results = search_vessels(mmsi)
    if not results:
        return None

    # Pick the result with the most AIS messages (most active identity)
    best = max(
        results,
        key=lambda r: (
            r.get("raw", {})
             .get("selfReportedInfo", [{}])[0]
             .get("messagesCounter", 0)
        ),
    )

    return {
        "id": best["id"],
        "name": display_name or best.get("shipname", f"MMSI {mmsi}"),
        "mmsi": mmsi,
        "flag": best.get("flag", "N/A"),
        "type": "fishing",
    }

@st.cache_data(show_spinner="Fetching vessel details...")
def get_vessel_details(vessel_id: str) -> dict | None:
    """
    Get registry and self-reported metadata for a single vessel.
    """
    url = f"{GFW_API_BASE_URL}/vessels/{vessel_id}"
    params = {
        "dataset": IDENTITY_DATASET
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code == 200:
            return r.json()
        else:
            logger.error("Vessel details fetch failed (Status %s): %s", r.status_code, r.text)
    except Exception as e:
        logger.error("Error in get_vessel_details: %s", e)
    return None

@st.cache_data(show_spinner="Fetching vessel events...")
def get_vessel_events(vessel_id: str, start_date: str, end_date: str) -> list[dict]:
    """
    Retrieve and consolidate fishing, loitering, encounters, and port visits
    for a vessel within a date range.
    """
    datasets = {
        "fishing": FISHING_DATASET,
        "loitering": LOITERING_DATASET,
        "encounter": ENCOUNTER_DATASET,
        "port_visit": PORT_VISIT_DATASET,
        "gap": GAP_DATASET
    }
    
    events_url = f"{GFW_API_BASE_URL}/events"
    consolidated_events = []
    
    for event_type, dataset_id in datasets.items():
        params = {
            "vessels[0]": vessel_id,
            "datasets[0]": dataset_id,
            "start-date": start_date,
            "end-date": end_date,
            "limit": 100,
            "offset": 0
        }
        try:
            r = requests.get(events_url, headers=headers, params=params, timeout=15)
            if r.status_code == 200:
                entries = r.json().get("entries", [])
                for entry in entries:
                    # Clean and parse coordinates
                    pos = entry.get("position", {})
                    lat = pos.get("lat")
                    lon = pos.get("lon")
                    
                    if lat is None or lon is None:
                        # Fallback to bounding box center if position is missing
                        bbox = entry.get("boundingBox")
                        if bbox and len(bbox) == 4:
                            lon = (bbox[0] + bbox[2]) / 2
                            lat = (bbox[1] + bbox[3]) / 2
                    
                    if lat is None or lon is None:
                        continue
                    
                    # Parse start and end times to calculate duration
                    start_time = entry.get("start")
                    end_time = entry.get("end")
                    duration_hrs = 0.0
                    if start_time and end_time:
                        try:
                            fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
                            dt_start = datetime.strptime(start_time.split(".")[0] + ".000Z", "%Y-%m-%dT%H:%M:%S.000Z")
                            dt_end = datetime.strptime(end_time.split(".")[0] + ".000Z", "%Y-%m-%dT%H:%M:%S.000Z")
                            duration_hrs = (dt_end - dt_start).total_seconds() / 3600.0
                        except Exception:
                            duration_hrs = 0.0
                    
                    # Store parsed details
                    event_data = {
                        "id": entry.get("id"),
                        "type": event_type,
                        "lat": float(lat),
                        "lon": float(lon),
                        "start": start_time,
                        "end": end_time,
                        "duration_hours": round(duration_hrs, 2),
                        "raw": entry
                    }
                    
                    # Add type-specific details
                    if event_type == "fishing":
                        fish = entry.get("fishing", {})
                        event_data["detail"] = f"Apparent fishing (speed: {fish.get('averageSpeedKnots', 0):.1f} kt, dist: {fish.get('totalDistanceKm', 0):.1f} km)"
                        event_data["metric"] = fish.get("averageSpeedKnots", 0.0)
                    elif event_type == "loitering":
                        loiter = entry.get("loitering", {})
                        event_data["detail"] = f"Loitering (average speed: {loiter.get('averageSpeedKnots', 0):.1f} kt)"
                        event_data["metric"] = loiter.get("averageSpeedKnots", 0.0)
                    elif event_type == "port_visit":
                        port = entry.get("portVisit", {})
                        port_name = port.get("portName") or "Unknown Port"
                        event_data["detail"] = f"Port Visit: {port_name} ({port.get('portFlag', 'N/A')})"
                        event_data["metric"] = port_name
                    elif event_type == "encounter":
                        encounter = entry.get("encounter", {})
                        other_v = encounter.get("vessel", {})
                        other_name = other_v.get("name") or "Unknown Vessel"
                        event_data["detail"] = f"Encounter with {other_name} ({other_v.get('flag', 'N/A')})"
                        event_data["metric"] = other_name
                    elif event_type == "gap":
                        gap = entry.get("gap", {})
                        event_data["detail"] = f"AIS Transmission Gap (duration: {event_data['duration_hours']:.1f} hrs)"
                        event_data["metric"] = event_data["duration_hours"]
                        
                    consolidated_events.append(event_data)
            else:
                logger.error("Failed to fetch %s events (Status %s): %s", event_type, r.status_code, r.text)
        except Exception as e:
            logger.error("Error fetching %s events: %s", event_type, e)
            
    # Sort chronologically by start time
    consolidated_events.sort(key=lambda x: x["start"] or "")
    return consolidated_events
