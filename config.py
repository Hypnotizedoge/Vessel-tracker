"""
config.py — Global Fishing Watch API configuration and vessel watchlist.

Vessels are loaded from 'vessels.xlsx' in the same directory.
The Excel file should have three columns: Company, Vessel Name, MMSI.
Just open it in Excel, add/remove rows, save, and restart the app.
"""

import os
import pandas as pd

# ---------------------------------------------------------------------------
# Global Fishing Watch API Token & Base URL
# ---------------------------------------------------------------------------
GFW_API_TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6ImtpZEtleSJ9.eyJkYXRhIjp7Im5hbWUiOiJTaGlwIHRyYWNrZXIiLCJ1c2VySWQiOjYzMDEwLCJhcHBsaWNhdGlvbk5hbWUiOiJTaGlwIHRyYWNrZXIiLCJpZCI6MTExMDMsInR5cGUiOiJ1c2VyLWFwcGxpY2F0aW9uIn0sImlhdCI6MTc3OTk1MzQ2NywiZXhwIjoyMDk1MzEzNDY3LCJhdWQiOiJnZnciLCJpc3MiOiJnZncifQ.Fd7dONE_4LfCx_8PeA8ENGC3_1Yfy8qOE4gLXJxJXbtLLBNYoi7E00foeXGWP6RjMZqXzJtul1JtbRIc-qyG3A8i65wlohUz7wvLOcivqpKZTEdr_cGw3lArre1ATTR7jPgmrcsOWju9qj415tseujQ8fCep4If-3cyIWDvMtpSpUd9IPVvtKwow_2airBYYRN3seU7SIQSrktAwuxG3Kc8TPoSEpzvjaQYhYeqMOCrdXvrPA0-qrtzeHDBWsXty03-mYZJgNXCvlHR9wY21J3Y5m_uPqlO5R7iXs1qxASlB51mz5ePkm0Qs7YFGocdccoiNiK1iRCSuIyAHSIWAuG5dQvxvBO8fmXRumgXZaVD3lrSsi2donFCZbNZxq0Jixh2Lug6FkV3u3S0Tue5y3-HlC4LcPobH7R6jMWGXV4RElGRf-R7kEN5pPz36EGwrIaxOjgPDthBsUoNi0DEimyiblcbdbIisYOiRqL26Df2V-H29Q0idmjil1trZKdUx"
GFW_API_BASE_URL = "https://gateway.api.globalfishingwatch.org/v3"

# Default Datasets
IDENTITY_DATASET = "public-global-vessel-identity:latest"
FISHING_DATASET = "public-global-fishing-events:latest"
LOITERING_DATASET = "public-global-loitering-events:latest"
ENCOUNTER_DATASET = "public-global-encounters-events:latest"
PORT_VISIT_DATASET = "public-global-port-visits-events:latest"
GAP_DATASET = "public-global-gaps-events:latest"

# ---------------------------------------------------------------------------
# Load vessel watchlist from Excel
# ---------------------------------------------------------------------------
_VESSELS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vessels.xlsx")


def load_watchlist() -> dict[str, list[dict]]:
    """
    Read vessels.xlsx and return a dict grouped by company.

    Returns:
        {
            "Company A": [
                {"name": "VESSEL", "mmsi": "567110155"},
                {"name": "FISHING VESSEL A", "mmsi": "412440306"},
            ],
            "Company B": [ ... ],
        }
    """
    if not os.path.exists(_VESSELS_FILE):
        return {"Default": []}

    df = pd.read_excel(_VESSELS_FILE, sheet_name="Watchlist", dtype=str)

    # Normalise column names (strip whitespace, lowercase)
    df.columns = df.columns.str.strip().str.lower()

    # Validate required columns
    required = {"company", "vessel name", "mmsi"}
    if not required.issubset(set(df.columns)):
        missing = required - set(df.columns)
        raise ValueError(
            f"vessels.xlsx is missing required columns: {missing}. "
            f"Expected: Company, Vessel Name, MMSI"
        )

    df = df.dropna(subset=["mmsi"])  # skip rows without an MMSI

    grouped: dict[str, list[dict]] = {}
    for _, row in df.iterrows():
        company = str(row.get("company", "Ungrouped")).strip() or "Ungrouped"
        vessel_name = str(row.get("vessel name", "Unknown")).strip()
        mmsi = str(row["mmsi"]).strip()

        grouped.setdefault(company, []).append({
            "name": vessel_name,
            "mmsi": mmsi,
        })

    return grouped if grouped else {"Default": []}


# Pre-load once at import time
VESSEL_COMPANIES: dict[str, list[dict]] = load_watchlist()
