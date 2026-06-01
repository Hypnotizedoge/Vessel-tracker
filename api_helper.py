import requests
import logging
import json
import os
from datetime import datetime, timedelta, date
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


def load_cached_events_from_csv(vessels: list[dict], start_date: date, end_date: date) -> list[dict]:
    """
    Load events exclusively from gfw_extracted_data.csv. No API calls are made.
    Filters the events to only match the selected vessels and requested date range.
    """
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gfw_extracted_data.csv")
    if not os.path.exists(csv_path):
        logger.info("CSV cache file does not exist at: %s", csv_path)
        return []
        
    try:
        df = pd.read_csv(csv_path, dtype=str)
        # Rename legacy columns if present
        rename_dict = {}
        if "activity" in df.columns:
            rename_dict["activity"] = "type"
        if "start_time" in df.columns:
            rename_dict["start_time"] = "start"
        if "end_time" in df.columns:
            rename_dict["end_time"] = "end"
        if rename_dict:
            df.rename(columns=rename_dict, inplace=True)
            
        # Parse numbers
        if "lat" in df.columns:
            df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        if "lon" in df.columns:
            df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
        if "duration_hours" in df.columns:
            df["duration_hours"] = pd.to_numeric(df["duration_hours"], errors="coerce")
            
        # Filter by vessel MMSI
        mmsis = [v["mmsi"] for v in vessels]
        if "vessel_mmsi" in df.columns:
            df = df[df["vessel_mmsi"].isin(mmsis)]
        else:
            return []
            
        if df.empty:
            return []
            
        # Filter by date range
        df["start_dt"] = pd.to_datetime(df["start"], errors="coerce")
        if hasattr(df["start_dt"].dtype, "tz") and df["start_dt"].dt.tz is not None:
            df["start_dt"] = df["start_dt"].dt.tz_localize(None)
            
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        
        mask = (df["start_dt"] >= start_dt) & (df["start_dt"] <= end_dt)
        filtered_df = df[mask].copy()
        filtered_df.drop(columns=["start_dt"], errors="ignore", inplace=True)
        
        # Sort chronologically
        if "start" in filtered_df.columns:
            filtered_df.sort_values(by="start", inplace=True)
            
        filtered_df = filtered_df.where(pd.notnull(filtered_df), None)
        return filtered_df.to_dict(orient="records")
    except Exception as e:
        logger.error("Error reading or filtering cached CSV file: %s", e)
        return []


def sync_vessels_with_api(vessels: list[dict]) -> dict:
    """
    Sync missing events from GFW API for the list of vessels.
    Uses gfw_sync_metadata.json to track the last sync date for each vessel.
    """
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gfw_extracted_data.csv")
    meta_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gfw_sync_metadata.json")
    
    # 1. Load sync metadata
    metadata = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception as e:
            logger.error("Error reading sync metadata file: %s", e)
            
    today_str = date.today().isoformat()
    new_events_list = []
    synced_count = 0
    total_new_events = 0
    
    for vessel in vessels:
        vessel_id = vessel["id"]
        mmsi = vessel["mmsi"]
        name = vessel["name"]
        
        # Determine last sync date
        last_synced_str = metadata.get(mmsi)
        if last_synced_str:
            try:
                last_synced = date.fromisoformat(last_synced_str)
            except Exception:
                last_synced = date.today() - timedelta(days=90)
        else:
            # Default to 90 days ago
            last_synced = date.today() - timedelta(days=90)
            
        api_start = last_synced + timedelta(days=1)
        api_end = date.today()
        
        if api_start <= api_end:
            logger.info("Syncing %s (MMSI: %s) -> Fetching GFW API from %s to %s", name, mmsi, api_start, api_end)
            fetched = get_vessel_events(vessel_id, api_start.isoformat(), api_end.isoformat())
            for e in fetched:
                e["vessel_name"] = name
                e["vessel_mmsi"] = mmsi
                e["vessel_flag"] = vessel.get("flag", "N/A")
                if "start" in e and e["start"]:
                    e["date"] = e["start"][:10]
                else:
                    e["date"] = ""
                new_events_list.append(e)
            
            total_new_events += len(fetched)
            synced_count += 1
            # Update sync date to today
            metadata[mmsi] = today_str
        else:
            logger.info("Syncing %s (MMSI: %s) -> Already synced to %s.", name, mmsi, last_synced)
            # Make sure it's set to today if it was somehow in the future
            metadata[mmsi] = today_str
            
    # Save sync metadata
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
    except Exception as e:
        logger.error("Failed to save sync metadata: %s", e)
        
    # Append to CSV and deduplicate
    if new_events_list or os.path.exists(csv_path):
        # Load existing data
        hist_df = pd.DataFrame()
        if os.path.exists(csv_path):
            try:
                hist_df = pd.read_csv(csv_path, dtype=str)
                # Map columns internally
                rename_dict = {}
                if "activity" in hist_df.columns:
                    rename_dict["activity"] = "type"
                if "start_time" in hist_df.columns:
                    rename_dict["start_time"] = "start"
                if "end_time" in hist_df.columns:
                    rename_dict["end_time"] = "end"
                if rename_dict:
                    hist_df.rename(columns=rename_dict, inplace=True)
            except Exception as e:
                logger.error("Failed to load CSV before append: %s", e)
                hist_df = pd.DataFrame()
                
        # Merge
        combined_df = hist_df
        if new_events_list:
            new_df = pd.DataFrame(new_events_list)
            if "raw" in new_df.columns:
                new_df.drop(columns=["raw"], inplace=True)
            if combined_df.empty:
                combined_df = new_df
            else:
                for col in new_df.columns:
                    if col not in combined_df.columns:
                        combined_df[col] = None
                for col in combined_df.columns:
                    if col not in new_df.columns:
                        new_df[col] = None
                combined_df = pd.concat([combined_df, new_df], ignore_index=True)
                
        if not combined_df.empty:
            # Deduplicate
            dup_subset = ["vessel_mmsi", "type", "start", "lat", "lon"]
            dup_subset = [col for col in dup_subset if col in combined_df.columns]
            combined_df.drop_duplicates(subset=dup_subset, keep="last", inplace=True)
            
            # Sort chronologically
            if "start" in combined_df.columns:
                combined_df.sort_values(by="start", inplace=True)
                
            # Rename back to legacy for compatibility
            save_df = combined_df.copy()
            save_rename = {}
            if "type" in save_df.columns:
                save_rename["type"] = "activity"
            if "start" in save_df.columns:
                save_rename["start"] = "start_time"
            if "end" in save_df.columns:
                save_rename["end"] = "end_time"
            if save_rename:
                save_df.rename(columns=save_rename, inplace=True)
                
            preferred_cols = [
                "vessel_name", "vessel_mmsi", "vessel_flag", "date", 
                "activity", "lat", "lon", "duration_hours", 
                "start_time", "end_time", "detail", "id"
            ]
            cols_to_save = [col for col in preferred_cols if col in save_df.columns]
            for col in save_df.columns:
                if col not in cols_to_save:
                    cols_to_save.append(col)
                    
            try:
                save_df[cols_to_save].to_csv(csv_path, index=False)
                logger.info("CSV cache updated successfully at %s", csv_path)
            except Exception as e:
                logger.error("Failed to write updated CSV cache: %s", e)
                
    return {
        "success": True,
        "vessels_synced": synced_count,
        "new_events_fetched": total_new_events
    }





