import os
import json
from threading import Lock
from django.conf import settings

STATS_FILE = os.path.join(settings.BASE_DIR, "halo_usage_stats.json")
stats_lock = Lock()
HALO_MAX_LIMIT = 5

def get_halo_usage(user_key: str) -> int:
    """
    Get the current message count for the given user identifier from the local JSON file.
    """
    with stats_lock:
        if not os.path.exists(STATS_FILE):
            return 0
        try:
            with open(STATS_FILE, "r") as f:
                stats = json.load(f)
            return stats.get(user_key, 0)
        except Exception:
            return 0

def increment_halo_usage(user_key: str) -> int:
    """
    Increment the message count for the given user identifier in the local JSON file.
    """
    with stats_lock:
        stats = {}
        if os.path.exists(STATS_FILE):
            try:
                with open(STATS_FILE, "r") as f:
                    stats = json.load(f)
            except Exception:
                stats = {}
        
        stats[user_key] = stats.get(user_key, 0) + 1
        
        try:
            with open(STATS_FILE, "w") as f:
                json.dump(stats, f, indent=4)
        except Exception:
            pass
            
        return stats[user_key]

BAYMAX_MAX_LIMIT = 5

def get_baymax_usage(user_key: str) -> int:
    """
    Get the current message count for the given user identifier (for Baymax model) from the local JSON file.
    """
    return get_halo_usage(f"baymax_{user_key}")

def increment_baymax_usage(user_key: str) -> int:
    """
    Increment the message count for the given user identifier (for Baymax model) in the local JSON file.
    """
    return increment_halo_usage(f"baymax_{user_key}")
