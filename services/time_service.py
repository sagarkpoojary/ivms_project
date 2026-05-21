import pytz
from datetime import datetime, timedelta
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

def parse_utc_time(time_str):
    """Parses standard ISO 8601 UTC time string and converts to Oman local datetime."""
    if not time_str:
        return None
    try:
        if time_str.endswith('Z'):
            dt = datetime.strptime(time_str, '%Y-%m-%dT%H:%M:%SZ')
            dt = pytz.utc.localize(dt)
        else:
            base = time_str[:19]
            dt = datetime.strptime(base, '%Y-%m-%dT%H:%M:%S')
            dt = pytz.utc.localize(dt)
        return dt.astimezone(SYSTEM_TZ)
    except:
        return None

def format_utc_to_oman_str(time_str):
    """Converts UTC time string to Oman local time string (YYYY-MM-DD HH:MM:SS)."""
    dt = parse_utc_time(time_str)
    if dt:
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    return time_str

def get_period_dates(period, from_str=None, to_str=None):
    now = get_oman_now()
    start_dt = now
    end_dt = now
    
    if period == 'Yesterday':
        start_dt = now - timedelta(days=1)
        start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt.replace(hour=23, minute=59, second=59, microsecond=999)
    elif period == 'This Week':
        start_dt = now - timedelta(days=now.weekday())
        start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now
    elif period == 'This Month':
        start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_dt = now
    elif period == 'Custom' and from_str:
        try:
            start_dt = datetime.strptime(from_str, '%Y-%m-%dT%H:%M')
            start_dt = SYSTEM_TZ.localize(start_dt)
            if to_str:
                end_dt = datetime.strptime(to_str, '%Y-%m-%dT%H:%M')
                end_dt = SYSTEM_TZ.localize(end_dt)
        except:
            pass
    else: # Today
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now
        
    return start_dt, end_dt
