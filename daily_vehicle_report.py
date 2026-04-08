import os
import requests
import pandas as pd
from datetime import datetime, timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
import pytz
from config import Config
Config.validate()

# --- CONFIGURATION (via Centralized Config) ---
API_BASE_URL = Config.IVMS_API_URL
API_TOKEN = Config.ODOO_REPORT_TOKEN

SMTP_SERVER = Config.SMTP_SERVER
SMTP_PORT = Config.SMTP_PORT
SMTP_USER = Config.SMTP_USER
SMTP_PASS = Config.SMTP_PASS
EMAIL_SENDER = Config.EMAIL_SENDER
EMAIL_RECIPIENTS = os.environ.get("REPORT_RECIPIENTS", "").split(",")

# Timezone
SYSTEM_TZ = pytz.timezone(Config.TIMEZONE)

def get_yesterday_oman():
    """Returns yesterday's date string in YYYY-MM-DD format for Oman."""
    now_oman = datetime.now(SYSTEM_TZ)
    yesterday = now_oman - timedelta(days=1)
    return yesterday.strftime('%Y-%m-%d')

def fetch_vehicle_list():
    """
    Fetches the list of vehicles via the IVMS headless API.
    Treats IVMS strictly as a black box.
    """
    try:
        url = f"{API_BASE_URL}/api/v1/vehicles"
        headers = {"Authorization": f"Bearer {API_TOKEN}"}
        response = requests.get(url, headers=headers, timeout=20)
        
        if response.status_code == 200:
            result = response.json()
            if result.get("status") == "success":
                # Return the list of vehicle_ids (IMEIs)
                return [str(v.get('vehicle_id')) for v in result.get('data', []) if v.get('vehicle_id')]
        
        print(f"Failed to fetch vehicle list via API: {response.status_code}")
        return []
    except Exception as e:
        print(f"Error fetching vehicle list via API: {e}")
        return []

def generate_report():
    yesterday_str = get_yesterday_oman()
    print(f"Generating Daily Report for: {yesterday_str}")
    
    vehicle_ids = fetch_vehicle_list()
    if not vehicle_ids:
        print("No vehicles found. Exiting.")
        return

    all_data = []
    headers = {"Authorization": f"Bearer {API_TOKEN}"}

    for vid in vehicle_ids:
        try:
            url = f"{API_BASE_URL}/api/v1/reports/vehicle-summary"
            params = {
                "vehicle_id": vid,
                "from_date": yesterday_str,
                "to_date": yesterday_str
            }
            response = requests.get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "success" and result.get("data"):
                    # The data is a list of daily stats (should be 1 item since from=to)
                    all_data.extend(result["data"])
            else:
                print(f"Failed to fetch data for {vid}: {response.status_code}")
        except Exception as e:
            print(f"Error fetching {vid}: {e}")

    if not all_data:
        print("No data collected for the report.")
        return

    # Convert to DataFrame
    df = pd.DataFrame(all_data)
    
    # Rename columns for professional look
    column_mapping = {
        "vehicle": "Vehicle ID (IMEI)",
        "date": "Date",
        "total_distance_km": "Total Distance (km)",
        "average_speed_kmph": "Average Speed (km/h)",
        "max_speed_kmph": "Max Speed (km/h)",
        "first_engine_on": "First Ignition ON",
        "last_engine_off": "Last Ignition OFF"
    }
    df = df.rename(columns=column_mapping)
    
    # Reorder columns
    cols = ["Date", "Vehicle ID (IMEI)", "Total Distance (km)", "Average Speed (km/h)", "Max Speed (km/h)", "First Ignition ON", "Last Ignition OFF"]
    df = df[cols]

    # Save to Excel
    filename = f"Daily_Vehicle_Summary_{yesterday_str}.xlsx"
    df.to_excel(filename, index=False, engine='openpyxl')
    print(f"Excel report generated: {filename}")
    
    send_email(filename, yesterday_str)
    
    # Cleanup
    if os.path.exists(filename):
        os.remove(filename)

def send_email(file_path, report_date):
    if not SMTP_USER or not EMAIL_RECIPIENTS[0]:
        print("SMTP credentials or recipients not configured. Skipping email.")
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = ", ".join(EMAIL_RECIPIENTS)
    msg['Subject'] = f"Daily IVMS Report - {report_date}"

    body = f"""
    <html>
    <body>
        <p>Dear Administrator,</p>
        <p>Please find attached the Daily Vehicle Summary Report for <b>{report_date}</b>.</p>
        <p>This report includes distance, speed, and ignition timings for all active vehicles.</p>
        <br>
        <p><i>This is an automated message from the IVMS System.</i></p>
    </body>
    </html>
    """
    msg.attach(MIMEText(body, 'html'))

    # Attach file
    with open(file_path, "rb") as attachment:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f"attachment; filename= {os.path.basename(file_path)}")
        msg.attach(part)

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        print(f"Email sent successfully to {len(EMAIL_RECIPIENTS)} recipients.")
    except Exception as e:
        print(f"Failed to send email: {e}")

if __name__ == "__main__":
    generate_report()
