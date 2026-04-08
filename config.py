import os
from dotenv import load_dotenv
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables
load_dotenv(BASE_DIR / '.env')

class Config:
    # Flask
    SECRET_KEY = os.environ.get("FLASK_SECRET")
    DEBUG = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    PORT = int(os.environ.get("FLASK_PORT", 5000))
    
    # Database
    DB_NAME = os.environ.get("DB_NAME")
    DB_USER = os.environ.get("DB_USER")
    DB_PASS = os.environ.get("DB_PASS")
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_PORT = os.environ.get("DB_PORT", "5432")
    
    # Traccar
    TRACCAR_IP = os.environ.get("TRACCAR_IP")
    TRACCAR_ADMIN_EMAIL = os.environ.get("TRACCAR_ADMIN_EMAIL")
    TRACCAR_ADMIN_PASS = os.environ.get("TRACCAR_ADMIN_PASS")
    
    # Reports & API
    IVMS_API_URL = os.environ.get("IVMS_API_URL")
    ODOO_REPORT_TOKEN = os.environ.get("ODOO_REPORT_TOKEN")
    
    # SMTP
    SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("SMTP_USER")
    SMTP_PASS = os.environ.get("SMTP_PASS")
    EMAIL_SENDER = os.environ.get("EMAIL_SENDER", SMTP_USER)
    
    # Localization
    TIMEZONE = os.environ.get("TIMEZONE", "Asia/Muscat")

    # Static / Cache
    CACHE_DIR = os.environ.get("CACHE_DIR", str(BASE_DIR / ".cache" / "flask_cache"))
    
    # Fuel & Calculations
    MILEAGE_KM_PER_LITER = float(os.environ.get("MILEAGE_KM_PER_LITER", 15.0))
    FUEL_PRICE_OMR = float(os.environ.get("FUEL_PRICE_OMR", 0.229))
    IDLE_FUEL_LPH = float(os.environ.get("IDLE_FUEL_LPH", 1.5)) # Liters per hour
    MAX_DATA_GAP_MINUTES = int(os.environ.get("MAX_DATA_GAP_MINUTES", 3))
    IDLE_SPEED_THRESHOLD = float(os.environ.get("IDLE_SPEED_THRESHOLD", 3.0)) # km/h
    
    @classmethod
    def validate(cls):
        required = [
            "SECRET_KEY", "DB_NAME", "DB_USER", "DB_PASS", 
            "IVMS_API_URL", "ODOO_REPORT_TOKEN", "SMTP_USER", "SMTP_PASS"
        ]
        missing = [key for key in required if not getattr(cls, key)]
        if missing:
            raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")
