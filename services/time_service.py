import pytz
from datetime import datetime

from config import Config

SYSTEM_TZ = pytz.timezone(Config.TIMEZONE)

def get_oman_now():
    """Returns the current time in system timezone."""
    return datetime.now(SYSTEM_TZ)

def format_to_oman(dt):
    """Converts a naive or aware datetime to Oman time and returns it as an aware datetime."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Assume it's UTC if naive
        dt = pytz.utc.localize(dt)
    return dt.astimezone(SYSTEM_TZ)

def parse_traccar_time(time_str):
    """Parses Traccar UTC time string and converts to Oman datetime."""
    if not time_str:
        return None
    try:
        # Traccar formats: 2023-10-27T10:00:00.000+00:00 or 2023-10-27T10:00:00Z
        if time_str.endswith('Z'):
            dt = datetime.strptime(time_str, '%Y-%m-%dT%H:%M:%SZ')
            dt = pytz.utc.localize(dt)
        else:
            # Handle float seconds or +00:00
            # Simplify by truncating to 19 chars if it's long
            base = time_str[:19]
            dt = datetime.strptime(base, '%Y-%m-%dT%H:%M:%S')
            dt = pytz.utc.localize(dt)
        return dt.astimezone(SYSTEM_TZ)
    except:
        return None

def parse_traccar_to_oman_str(time_str):
    """Converts Traccar UTC time string to Oman local time string (YYYY-MM-DD HH:MM:SS)."""
    dt = parse_traccar_time(time_str)
    if dt:
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    return time_str # Return original if parsing fails
