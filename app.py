"""
app.py — Global Fishing Watch Vessel Tracker Dashboard

A clean, sidebar-free Streamlit dashboard that tracks and analyzes
fishing vessels grouped by company. Reads vessel list from vessels.xlsx.
"""

import datetime
import pandas as pd
import numpy as np
import altair as alt
import folium
import streamlit as st
from streamlit_folium import st_folium

from config import VESSEL_COMPANIES
from api_helper import search_vessels, get_vessel_details, get_vessel_events, resolve_vessel_by_mmsi

# ---------------------------------------------------------------------------
# Page configuration — NO sidebar
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Fleet Vessel Tracker",
    page_icon="🚢",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Distinct vessel colors (up to 12 vessels per company)
# ---------------------------------------------------------------------------
VESSEL_PALETTE = [
    "#3b82f6",  # Blue
    "#ef4444",  # Red
    "#10b981",  # Emerald
    "#f59e0b",  # Amber
    "#8b5cf6",  # Purple
    "#ec4899",  # Pink
    "#14b8a6",  # Teal
    "#f97316",  # Orange
    "#6366f1",  # Indigo
    "#84cc16",  # Lime
    "#06b6d4",  # Cyan
    "#e11d48",  # Rose
]

EVENT_COLORS = {
    "fishing": "#ef4444",
    "loitering": "#f59e0b",
    "port_visit": "#10b981",
    "encounter": "#3b82f6",
    "gap": "#8b5cf6",
}

# ---------------------------------------------------------------------------
# Premium dark-mode CSS — no sidebar
# ---------------------------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
html, body, [class*="st-"] { font-family: 'Inter', sans-serif; }

/* Hide sidebar completely */
section[data-testid="stSidebar"] { display: none !important; }
button[data-testid="stSidebarCollapseButton"],
button[data-testid="stSidebarNavToggle"] { display: none !important; }
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }

.main .block-container { padding-top: 1.2rem; max-width: 1500px; }

/* Header */
.dash-header {
    background: linear-gradient(135deg, #051923 0%, #003554 50%, #006494 100%);
    border-radius: 14px; padding: 1.6rem 2.2rem; margin-bottom: 1rem;
    border: 1px solid rgba(255,255,255,0.08);
    display: flex; justify-content: space-between; align-items: center;
}
.dash-header .left h1 { color: #f8fafc; font-size: 1.65rem; font-weight: 700; margin: 0; }
.dash-header .left p  { color: #94a3b8; font-size: 0.88rem; margin-top: 0.25rem; }
.dash-header .right   { color: #64748b; font-size: 0.78rem; text-align: right; }

/* Filter bar */
.filter-bar {
    background: linear-gradient(145deg, rgba(11,30,44,0.95), rgba(7,19,30,0.95));
    backdrop-filter: blur(12px);
    border-radius: 12px; padding: 1rem 1.5rem; margin-bottom: 1.4rem;
    border: 1px solid rgba(255,255,255,0.06);
}

/* KPI cards */
.kpi {
    background: linear-gradient(145deg, #0b1e2c, #07131e);
    border-radius: 12px; padding: 1.2rem; text-align: center;
    border: 1px solid rgba(255,255,255,0.06);
    transition: transform 0.2s, box-shadow 0.2s;
}
.kpi:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,0.4); }
.kpi .label { color: #94a3b8; font-size: 0.7rem; text-transform: uppercase;
              letter-spacing: 0.08em; margin-bottom: 0.3rem; }
.kpi .value { font-size: 1.9rem; font-weight: 700; line-height: 1.1; }
.kpi.blue   .value { color: #3b82f6; }
.kpi.green  .value { color: #10b981; }
.kpi.amber  .value { color: #f59e0b; }
.kpi.purple .value { color: #a855f7; }
.kpi.cyan   .value { color: #06b6d4; }

/* Vessel legend */
.vessel-legend {
    display: flex; flex-wrap: wrap; gap: 0.8rem; margin: 0.8rem 0;
}
.vessel-chip {
    display: inline-flex; align-items: center; gap: 6px;
    background: rgba(255,255,255,0.04); border-radius: 8px;
    padding: 0.35rem 0.75rem; font-size: 0.78rem; color: #cbd5e1;
    border: 1px solid rgba(255,255,255,0.06);
}
.vessel-dot {
    width: 10px; height: 10px; border-radius: 50%; display: inline-block;
}

/* Empty state */
.empty { text-align: center; padding: 3rem 2rem; color: #64748b; }
.empty h3 { color: #94a3b8; font-size: 1.1rem; }

/* Registry card */
.reg-card {
    background: linear-gradient(145deg, #0b1e2c, #07131e);
    border-radius: 12px; padding: 1.4rem; margin-bottom: 1rem;
    border: 1px solid rgba(255,255,255,0.06);
}
.reg-card h4 { color: #f8fafc; margin: 0 0 0.6rem 0; font-size: 1rem; }
.reg-card .meta { color: #94a3b8; font-size: 0.82rem; margin-bottom: 0.2rem; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Dashboard Header
# ---------------------------------------------------------------------------
st.markdown("""
<div class="dash-header">
  <div class="left">
    <h1>🚢 Fleet Vessel Tracker</h1>
    <p>Track vessel paths and detect apparent fishing, loitering, port visits, and encounters using GFW API v3.</p>
  </div>
  <div class="right">
    Powered by Global Fishing Watch<br>Data from AIS transponders
  </div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Inline Filter Bar (replaces sidebar)
# ---------------------------------------------------------------------------
company_names = list(VESSEL_COMPANIES.keys())

if not company_names or (len(company_names) == 1 and not VESSEL_COMPANIES.get(company_names[0])):
    st.error("No vessels found in **vessels.xlsx**. Add Company / Vessel Name / MMSI rows and restart.")
    st.stop()

fil_c1, fil_c2, fil_c3 = st.columns([3, 1.5, 1.5])

with fil_c1:
    selected_company = st.selectbox(
        "Company",
        company_names,
        label_visibility="collapsed",
        help="Select a company to view its fleet",
    )

default_end = datetime.date.today()
default_start = default_end - datetime.timedelta(days=60)

with fil_c2:
    start_date = st.date_input("Start Date", value=default_start)

with fil_c3:
    end_date = st.date_input("End Date", value=default_end)

# ---------------------------------------------------------------------------
# Resolve all vessels in the selected company
# ---------------------------------------------------------------------------
vessels_in_company = VESSEL_COMPANIES.get(selected_company, [])

if not vessels_in_company:
    st.warning(f"No vessels listed under **{selected_company}**. Add rows in vessels.xlsx.")
    st.stop()

resolved_vessels: list[dict] = []
for v in vessels_in_company:
    resolved = resolve_vessel_by_mmsi(v["mmsi"], display_name=v["name"])
    if resolved:
        resolved_vessels.append(resolved)

if not resolved_vessels:
    st.error("Could not resolve any vessels from Global Fishing Watch. Check the MMSI numbers in vessels.xlsx.")
    st.stop()

# Assign a color to each vessel
for idx, rv in enumerate(resolved_vessels):
    rv["color"] = VESSEL_PALETTE[idx % len(VESSEL_PALETTE)]

# ---------------------------------------------------------------------------
# Fetch events for ALL vessels in the company
# ---------------------------------------------------------------------------
all_events: list[dict] = []
for vessel in resolved_vessels:
    events = get_vessel_events(vessel["id"], start_date.isoformat(), end_date.isoformat())
    for e in events:
        e["vessel_name"] = vessel["name"]
        e["vessel_mmsi"] = vessel["mmsi"]
        e["vessel_color"] = vessel["color"]
    all_events.extend(events)

# Sort chronologically
all_events.sort(key=lambda x: x.get("start") or "")

# ---------------------------------------------------------------------------
# Vessel color legend
# ---------------------------------------------------------------------------
legend_html = '<div class="vessel-legend">'
for rv in resolved_vessels:
    legend_html += (
        f'<span class="vessel-chip">'
        f'<span class="vessel-dot" style="background:{rv["color"]};"></span>'
        f'{rv["name"]} ({rv["mmsi"]})'
        f'</span>'
    )
legend_html += '</div>'

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab1, tab2, tab3 = st.tabs(["🗺️ Vessel Tracking", "📊 Historical Analysis", "📋 Fleet Registry"])

# ═══════════════════════════════════════════════════════════════════════════
# TAB 1 — VESSEL TRACKING (multi-vessel map)
# ═══════════════════════════════════════════════════════════════════════════
with tab1:
    if not all_events:
        st.markdown(
            f'<div class="empty"><h3>No Events Found</h3>'
            f'<p>No maritime events detected for <b>{selected_company}</b> '
            f'from <b>{start_date}</b> to <b>{end_date}</b>.<br>'
            f'Try adjusting the date range.</p></div>',
            unsafe_allow_html=True,
        )
    else:
        # ── KPI Cards (aggregated across fleet) ──────────────────────────
        df_events = pd.DataFrame(all_events)

        total_vessels = len(resolved_vessels)
        active_days = len(set(
            e["start"].split("T")[0] for e in all_events if e.get("start")
        ))
        fishing_hours = df_events[df_events["type"] == "fishing"]["duration_hours"].sum()
        port_visits_count = len(df_events[df_events["type"] == "port_visit"])
        encounters_count = len(df_events[df_events["type"] == "encounter"])

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.markdown(
            f'<div class="kpi cyan"><div class="label">Fleet Vessels</div>'
            f'<div class="value">{total_vessels}</div></div>',
            unsafe_allow_html=True,
        )
        c2.markdown(
            f'<div class="kpi blue"><div class="label">Active Days</div>'
            f'<div class="value">{active_days}</div></div>',
            unsafe_allow_html=True,
        )
        c3.markdown(
            f'<div class="kpi green"><div class="label">Fishing Hours</div>'
            f'<div class="value">{fishing_hours:,.1f}h</div></div>',
            unsafe_allow_html=True,
        )
        c4.markdown(
            f'<div class="kpi amber"><div class="label">Port Visits</div>'
            f'<div class="value">{port_visits_count}</div></div>',
            unsafe_allow_html=True,
        )
        c5.markdown(
            f'<div class="kpi purple"><div class="label">Encounters</div>'
            f'<div class="value">{encounters_count}</div></div>',
            unsafe_allow_html=True,
        )

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Vessel legend ────────────────────────────────────────────────
        st.markdown(legend_html, unsafe_allow_html=True)

        # ── Event type filters ───────────────────────────────────────────
        event_types = sorted(df_events["type"].unique().tolist())
        selected_types = []
        if event_types:
            filter_cols = st.columns(len(event_types))
            for idx, etype in enumerate(event_types):
                label = etype.replace("_", " ").title()
                count = len(df_events[df_events["type"] == etype])
                if filter_cols[idx].checkbox(
                    f"{label} ({count})", value=True, key=f"track_filter_{etype}"
                ):
                    selected_types.append(etype)

        filtered_events = [e for e in all_events if e["type"] in selected_types]

        # ── Multi-vessel Folium map ──────────────────────────────────────
        if filtered_events:
            center_lat = sum(e["lat"] for e in filtered_events) / len(filtered_events)
            center_lon = sum(e["lon"] for e in filtered_events) / len(filtered_events)

            m = folium.Map(
                location=[center_lat, center_lon],
                zoom_start=5,
                tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
                attr="Google Satellite",
                control_scale=True,
            )

            # Draw path lines per vessel
            for vessel in resolved_vessels:
                v_events = [
                    e for e in all_events if e["vessel_mmsi"] == vessel["mmsi"]
                ]
                coords = [[e["lat"], e["lon"]] for e in v_events]
                if len(coords) >= 2:
                    folium.PolyLine(
                        locations=coords,
                        color=vessel["color"],
                        weight=2.5,
                        opacity=0.7,
                        dash_array="6, 8",
                        tooltip=f"{vessel['name']} — Journey Path",
                    ).add_to(m)

            # Add markers for filtered events
            for e in filtered_events:
                etype_str = e["type"].replace("_", " ").upper()
                evt_color = EVENT_COLORS.get(e["type"], "#ffffff")
                vessel_color = e["vessel_color"]

                tooltip_html = f"""
                <div style="font-family:Inter,sans-serif;font-size:12px;padding:5px;min-width:200px;">
                  <b style="color:{vessel_color};">{e['vessel_name']}</b><br>
                  <b>Event:</b> <span style="color:{evt_color};font-weight:bold;">{etype_str}</span><br>
                  <b>Start:</b> {e['start']}<br>
                  <b>End:</b> {e['end']}<br>
                  <b>Duration:</b> {e['duration_hours']:.1f} hrs<br>
                  <b>Details:</b> {e['detail']}
                </div>
                """

                folium.CircleMarker(
                    location=[e["lat"], e["lon"]],
                    radius=6,
                    color=vessel_color,
                    weight=1.5,
                    fill=True,
                    fill_color=vessel_color,
                    fill_opacity=0.8,
                    tooltip=tooltip_html,
                ).add_to(m)

            st_folium(m, use_container_width=True, height=520)
        else:
            st.info("Select at least one event type filter to view events on the map.")

        # ── Events log table ─────────────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### Events Log")
        display_df = pd.DataFrame([
            {
                "Vessel": e["vessel_name"],
                "Event Type": e["type"].replace("_", " ").title(),
                "Start Time": e["start"],
                "End Time": e["end"],
                "Duration (h)": e["duration_hours"],
                "Lat": e["lat"],
                "Lon": e["lon"],
                "Details": e["detail"],
            }
            for e in filtered_events
        ])

        if not display_df.empty:
            st.dataframe(
                display_df.sort_values("Start Time", ascending=False),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No events to display.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 2 — HISTORICAL ANALYSIS (company-aggregated)
# ═══════════════════════════════════════════════════════════════════════════
with tab2:
    if not all_events:
        st.info("No historical event data to analyze for this company and date range.")
    else:
        st.markdown("### Fleet Activity Analysis")
        st.markdown(legend_html, unsafe_allow_html=True)

        df_hist = pd.DataFrame(all_events)
        df_hist["date"] = pd.to_datetime(df_hist["start"]).dt.date
        df_hist["duration_hours"] = df_hist["duration_hours"].astype(float)

        # ── Chart 1: Timeline by vessel ──────────────────────────────────
        st.markdown("#### Daily Event Count by Vessel")

        timeline_data = (
            df_hist.groupby(["date", "vessel_name"])
            .size()
            .reset_index(name="count")
        )
        timeline_data["date"] = pd.to_datetime(timeline_data["date"])

        vessel_names = [v["name"] for v in resolved_vessels]
        vessel_colors = [v["color"] for v in resolved_vessels]

        chart_timeline = (
            alt.Chart(timeline_data)
            .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(
                x=alt.X("date:T", title="Date", axis=alt.Axis(format="%d %b %Y")),
                y=alt.Y("count:Q", title="Events"),
                color=alt.Color(
                    "vessel_name:N",
                    title="Vessel",
                    scale=alt.Scale(domain=vessel_names, range=vessel_colors),
                ),
                tooltip=["date:T", "vessel_name:N", "count:Q"],
            )
            .properties(height=300)
        )
        st.altair_chart(chart_timeline, use_container_width=True)

        # ── Chart 2 & 3: Duration + Proportions ─────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        col_c1, col_c2, col_c3 = st.columns(3)

        with col_c1:
            st.markdown("#### Event Durations by Type")
            dur_data = df_hist.groupby("type")["duration_hours"].sum().reset_index()
            dur_data["Event Type"] = dur_data["type"].str.replace("_", " ").str.title()

            chart_dur = (
                alt.Chart(dur_data)
                .mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3)
                .encode(
                    x=alt.X("duration_hours:Q", title="Total Hours"),
                    y=alt.Y("Event Type:N", sort="-x", title=None),
                    color=alt.Color(
                        "Event Type:N",
                        scale=alt.Scale(
                            domain=[t.replace("_", " ").title() for t in EVENT_COLORS],
                            range=list(EVENT_COLORS.values()),
                        ),
                        legend=None,
                    ),
                    tooltip=[
                        "Event Type",
                        alt.Tooltip("duration_hours:Q", title="Hours", format=".1f"),
                    ],
                )
                .properties(height=250)
            )
            st.altair_chart(chart_dur, use_container_width=True)

        with col_c2:
            st.markdown("#### Event Proportions")
            pie_data = df_hist.groupby("type").size().reset_index(name="count")
            pie_data["Event Type"] = pie_data["type"].str.replace("_", " ").str.title()

            chart_pie = (
                alt.Chart(pie_data)
                .mark_arc(innerRadius=40)
                .encode(
                    theta=alt.Theta("count:Q"),
                    color=alt.Color(
                        "Event Type:N",
                        scale=alt.Scale(
                            domain=[t.replace("_", " ").title() for t in EVENT_COLORS],
                            range=list(EVENT_COLORS.values()),
                        ),
                    ),
                    tooltip=["Event Type", "count"],
                )
                .properties(height=250)
            )
            st.altair_chart(chart_pie, use_container_width=True)

        with col_c3:
            st.markdown("#### Events per Vessel")
            vessel_event_counts = (
                df_hist.groupby("vessel_name").size().reset_index(name="count")
            )

            chart_vessel = (
                alt.Chart(vessel_event_counts)
                .mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3)
                .encode(
                    x=alt.X("count:Q", title="Total Events"),
                    y=alt.Y("vessel_name:N", sort="-x", title=None),
                    color=alt.Color(
                        "vessel_name:N",
                        title="Vessel",
                        scale=alt.Scale(domain=vessel_names, range=vessel_colors),
                        legend=None,
                    ),
                    tooltip=["vessel_name:N", "count:Q"],
                )
                .properties(height=250)
            )
            st.altair_chart(chart_vessel, use_container_width=True)

        # ── Chart 4: Fishing hours per vessel breakdown ──────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### Fishing Hours by Vessel")

        fishing_by_vessel = (
            df_hist[df_hist["type"] == "fishing"]
            .groupby("vessel_name")["duration_hours"]
            .sum()
            .reset_index()
        )

        if not fishing_by_vessel.empty:
            chart_fishing = (
                alt.Chart(fishing_by_vessel)
                .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                .encode(
                    x=alt.X("vessel_name:N", title=None, sort="-y"),
                    y=alt.Y("duration_hours:Q", title="Fishing Hours"),
                    color=alt.Color(
                        "vessel_name:N",
                        title="Vessel",
                        scale=alt.Scale(domain=vessel_names, range=vessel_colors),
                        legend=None,
                    ),
                    tooltip=[
                        "vessel_name:N",
                        alt.Tooltip("duration_hours:Q", title="Hours", format=".1f"),
                    ],
                )
                .properties(height=280)
            )
            st.altair_chart(chart_fishing, use_container_width=True)
        else:
            st.info("No fishing events recorded in this date range.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 3 — FLEET REGISTRY (all vessels in the company)
# ═══════════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown(f"### {selected_company} — Fleet Registry")
    st.markdown(legend_html, unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    # Fetch details for every vessel and build a fleet table
    fleet_rows: list[dict] = []
    detailed_registries: list[tuple[dict, dict | None]] = []

    for vessel in resolved_vessels:
        details = get_vessel_details(vessel["id"])
        detailed_registries.append((vessel, details))

        info = {}
        registry = {}
        if details:
            info = (
                details.get("selfReportedInfo", [{}])[0]
                if details.get("selfReportedInfo")
                else {}
            )
            registry = (
                details.get("registryInfo", [{}])[0]
                if details.get("registryInfo")
                else {}
            )

        # Extract characteristics
        reg_list = details.get("registryInfo", []) if details else []
        length = "N/A"
        tonnage = "N/A"
        power = "N/A"

        if reg_list:
            l_val = next((r.get("lengthM") for r in reg_list if r.get("lengthM")), None)
            if l_val:
                length = f"{l_val:.1f} m"
            t_val = next((r.get("tonnageGt") for r in reg_list if r.get("tonnageGt")), None)
            if t_val:
                tonnage = f"{t_val:.1f} GT"
            p_val = next(
                (r.get("enginePowerKw") for r in reg_list if r.get("enginePowerKw")),
                None,
            )
            if p_val:
                power = f"{p_val:.1f} kW"

        # Transmission period
        tx_from = info.get("transmissionDateFrom", "N/A")
        tx_to = info.get("transmissionDateTo", "N/A")
        if tx_from and tx_from != "N/A":
            tx_from = tx_from[:10]
        if tx_to and tx_to != "N/A":
            tx_to = tx_to[:10]

        fleet_rows.append(
            {
                "Vessel Name": vessel["name"],
                "MMSI": vessel["mmsi"],
                "Flag": info.get("flag") or registry.get("flag", vessel.get("flag", "N/A")),
                "IMO": info.get("imo") or registry.get("imo", "N/A"),
                "Call Sign": info.get("callsign") or registry.get("callsign", "N/A"),
                "Length": length,
                "Tonnage": tonnage,
                "Engine Power": power,
                "Transmitting From": tx_from,
                "Transmitting To": tx_to,
                "GFW Vessel ID": vessel["id"],
            }
        )

    # ── Fleet overview table ─────────────────────────────────────────
    st.markdown("#### Fleet Overview")
    fleet_df = pd.DataFrame(fleet_rows)
    st.dataframe(fleet_df, use_container_width=True, hide_index=True)

    # ── Per-vessel detailed registry cards ───────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("#### Vessel Registry Details")

    for vessel, details in detailed_registries:
        with st.expander(f"🚢 {vessel['name']}  ({vessel['mmsi']})", expanded=False):
            if not details:
                st.warning("Registry metadata could not be fetched.")
                continue

            col_r1, col_r2 = st.columns(2)

            with col_r1:
                st.markdown("**Identifiers**")
                info = (
                    details.get("selfReportedInfo", [{}])[0]
                    if details.get("selfReportedInfo")
                    else {}
                )
                registry = (
                    details.get("registryInfo", [{}])[0]
                    if details.get("registryInfo")
                    else {}
                )

                id_df = pd.DataFrame(
                    [
                        {"Field": "Shipname", "Value": info.get("shipname") or registry.get("shipname", "N/A")},
                        {"Field": "MMSI", "Value": info.get("ssvid") or registry.get("ssvid", "N/A")},
                        {"Field": "Flag", "Value": info.get("flag") or registry.get("flag", "N/A")},
                        {"Field": "IMO", "Value": info.get("imo") or registry.get("imo", "N/A")},
                        {"Field": "Call Sign", "Value": info.get("callsign") or registry.get("callsign", "N/A")},
                    ]
                )
                st.dataframe(id_df, use_container_width=True, hide_index=True)

            with col_r2:
                st.markdown("**Registry History**")
                reg_records = []
                for r in details.get("registryInfo", []):
                    reg_records.append(
                        {
                            "Source": r.get("sourceCode", "N/A"),
                            "Name": r.get("shipname", "N/A"),
                            "Flag": r.get("flag", "N/A"),
                            "Length (m)": r.get("lengthM", "N/A"),
                            "Tonnage (GT)": r.get("tonnageGt", "N/A"),
                            "From": (r.get("transmissionDateFrom", "N/A")[:10] if r.get("transmissionDateFrom") else "N/A"),
                            "To": (r.get("transmissionDateTo", "N/A")[:10] if r.get("transmissionDateTo") else "N/A"),
                        }
                    )

                if reg_records:
                    st.dataframe(
                        pd.DataFrame(reg_records),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("No registry records found.")
