import os
import sys
import logging
from config import load_watchlist
from api_helper import resolve_vessel_by_mmsi, sync_vessels_with_api

# Set up logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("run_sync")

def main():
    logger.info("Starting daily GFW vessel data sync...")
    
    # 1. Load watchlist from Excel
    try:
        watchlist = load_watchlist()
    except Exception as e:
        logger.error("Failed to load vessel watchlist from vessels.xlsx: %s", e)
        sys.exit(1)
        
    # Flatten watchlist companies into a single list
    vessels_to_resolve = []
    for company, vessels in watchlist.items():
        for v in vessels:
            vessels_to_resolve.append((v["name"], v["mmsi"]))
            
    if not vessels_to_resolve:
        logger.warning("No vessels found in vessels.xlsx.")
        sys.exit(0)
        
    logger.info("Found %d vessels in watchlist.", len(vessels_to_resolve))
    
    # 2. Resolve all vessels to GFW IDs
    resolved_vessels = []
    for name, mmsi in vessels_to_resolve:
        logger.info("Resolving %s (MMSI: %s)...", name, mmsi)
        try:
            # We call resolve_vessel_by_mmsi, which will call the GFW API and get the GFW id
            resolved = resolve_vessel_by_mmsi(mmsi, name)
            if resolved:
                logger.info("  -> GFW ID: %s, Flag: %s", resolved["id"], resolved["flag"])
                resolved_vessels.append(resolved)
            else:
                logger.warning("  -> Failed to resolve vessel by MMSI on GFW API.")
        except Exception as e:
            logger.error("  -> Error resolving vessel: %s", e)
            
    if not resolved_vessels:
        logger.error("Failed to resolve any vessels. Sync aborted.")
        sys.exit(1)
        
    # 3. Trigger incremental sync
    logger.info("Triggering sync for %d vessels...", len(resolved_vessels))
    try:
        sync_result = sync_vessels_with_api(resolved_vessels)
        logger.info("Sync completed: %s", sync_result)
    except Exception as e:
        logger.error("Sync failed: %s", e)
        sys.exit(1)
        
    logger.info("Vessel data sync script finished successfully.")

if __name__ == "__main__":
    main()
