from backend.models import AnonymousUsage

HALO_MAX_LIMIT = 5
BAYMAX_MAX_LIMIT = 5

def get_halo_usage(user_key: str) -> int:
    """
    Get the current message count for the given user identifier from the database.
    """
    usage, _ = AnonymousUsage.objects.get_or_create(user_key=user_key)
    return usage.message_count

def increment_halo_usage(user_key: str) -> int:
    """
    Increment the message count for the given user identifier in the database.
    """
    usage, _ = AnonymousUsage.objects.get_or_create(user_key=user_key)
    usage.message_count += 1
    usage.save(update_fields=['message_count', 'updated_at'])
    return usage.message_count

def get_baymax_usage(user_key: str) -> int:
    """
    Get the current message count for the given user identifier (for Baymax model).
    """
    return get_halo_usage(f"baymax_{user_key}")

def increment_baymax_usage(user_key: str) -> int:
    """
    Increment the message count for the given user identifier (for Baymax model).
    """
    return increment_halo_usage(f"baymax_{user_key}")

