import os
import re
import json
import requests
import psycopg2
import psycopg2.extras
from datetime import datetime
from config import Config
from models.database import get_conn

class AIService:
    TABLE_WHITELIST = {
        "vehicles",
        "live_vehicle_status",
        "telemetry",
        "trip_summary",
        "analytics_events",
        "driver_sessions",
        "drivers",
        "rfid_events"
    }

    def __init__(self):
        # Dynamically initialize the additive ai_logs table if not exists
        self._init_db_table()

    def _init_db_table(self):
        conn = None
        cur = None
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ai_logs (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    query TEXT NOT NULL,
                    response TEXT,
                    type VARCHAR(50),
                    status VARCHAR(20),
                    tokens INTEGER DEFAULT 0,
                    error TEXT
                );
            """)
            conn.commit()
            cur.close(); conn.close()
        except Exception as e:
            print(f"Failed to initialize ai_logs table: {e}")
            if cur:
                try: cur.close()
                except: pass
            if conn:
                try: conn.rollback(); conn.close()
                except: pass

    def get_logs(self):
        conn = None
        cur = None
        try:
            conn = get_conn()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # Fetch last 20 logs
            cur.execute("SELECT * FROM ai_logs ORDER BY timestamp DESC LIMIT 20;")
            logs = [dict(r) for r in cur.fetchall()]
            
            # Fetch sum of tokens
            cur.execute("SELECT COALESCE(SUM(tokens), 0) as total_tokens FROM ai_logs;")
            row = cur.fetchone()
            token_count = row["total_tokens"] if row else 0
            
            cur.close(); conn.close()
            
            # ISO format dates for json serialization compatibility
            for l in logs:
                if isinstance(l.get("timestamp"), datetime):
                    l["timestamp"] = l["timestamp"].isoformat()
                    
            return {"logs": logs, "token_count": token_count}
        except Exception as e:
            print(f"Failed to fetch logs: {e}")
            if cur:
                try: cur.close()
                except: pass
            if conn:
                try: conn.close()
                except: pass
            return {"logs": [], "token_count": 0}

    def add_log(self, query, response, r_type, status, tokens=0, error=""):
        conn = None
        cur = None
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO ai_logs (query, response, type, status, tokens, error)
                VALUES (%s, %s, %s, %s, %s, %s);
            """, (query, response, r_type, status, tokens, error))
            conn.commit()
            cur.close(); conn.close()
        except Exception as e:
            print(f"Failed to add log entry: {e}")
            if cur:
                try: cur.close()
                except: pass
            if conn:
                try: conn.rollback(); conn.close()
                except: pass

    def load_config(self):
        try:
            conn = get_conn()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT data FROM system_config WHERE doc_id = %s", ("ai_config",))
            row = cur.fetchone()
            cur.close(); conn.close()
            if row:
                return dict(row["data"])
        except:
            pass
            
        # Default fallback config
        return {
            "api_key": "",
            "model": "gpt-4o",
            "endpoint": "https://api.openai.com/v1",
            "system_prompt": "You are Antigravity, an intelligent assistant inside the Intelligent Vehicle Monitoring System (IVMS).\nUse tables and bullet points to summarize fleet data. Be professional, direct, and detailed.",
            "allow_db": True,
            "rag_enabled": True,
            "language": "en"
        }

    def save_config(self, config_data):
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO system_config (doc_id, data) VALUES (%s, %s) "
                "ON CONFLICT (doc_id) DO UPDATE SET data = EXCLUDED.data",
                ("ai_config", psycopg2.extras.Json(config_data))
            )
            conn.commit()
            cur.close(); conn.close()
            return True
        except Exception as e:
            print(f"save_config error: {e}")
            return False

    def test_connection(self, config):
        api_key = config.get("api_key", "").strip()
        endpoint = config.get("endpoint", "https://api.openai.com/v1").strip().rstrip('/')
        model = config.get("model", "gpt-4o")
        
        url = f"{endpoint}/chat/completions"
        headers = {
            "Content-Type": "application/json"
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5
        }
        
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=8.0)
            if r.status_code == 200:
                return True, "Connection successful."
            else:
                return False, f"API returned error status {r.status_code}: {r.text}"
        except Exception as e:
            return False, f"Connection failed: {e}"

    def ask_ai(self, messages, config=None):
        if not config:
            config = self.load_config()
            
        api_key = config.get("api_key", "").strip()
        endpoint = config.get("endpoint", "https://api.openai.com/v1").strip().rstrip('/')
        model = config.get("model", "gpt-4o")
        
        # Friendly UX check: Intercept missing key for public OpenAI endpoint
        if not api_key and ("openai.com" in endpoint or endpoint == "https://api.openai.com/v1"):
            return False, (
                "**OpenAI API Key Missing**\n\n"
                "To enable fleet queries and diagnostic analysis, please:\n"
                "1. Go to the [AI Agent Settings](/ai/settings) panel.\n"
                "2. Paste your secret key in the **API Secret Key** input field.\n"
                "3. Click **Save Configurations**.\n\n"
                "*If you are running a local LLM (e.g. Ollama), update the endpoint URL and select the corresponding model.*"
            ), 0
        
        url = f"{endpoint}/chat/completions"
        headers = {
            "Content-Type": "application/json"
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # Setup standard system prompt
        sys_msg = {"role": "system", "content": config.get("system_prompt", "")}
        full_messages = [sys_msg] + messages

        payload = {
            "model": model,
            "messages": full_messages,
            "temperature": 0.3
        }

        try:
            r = requests.post(url, json=payload, headers=headers, timeout=25.0)
            if r.status_code == 200:
                resp_json = r.json()
                content = resp_json["choices"][0]["message"]["content"]
                tokens = resp_json.get("usage", {}).get("total_tokens", 0)
                return True, content, tokens
            else:
                return False, f"API Error: {r.status_code} - {r.text}", 0
        except Exception as e:
            return False, f"Request failed: {e}", 0

    def parse_and_validate_sql(self, sql):
        """
        Strict SQL Enforcer to guarantee database safety.
        Returns (is_valid, sanitized_sql, error_message)
        """
        # Strip trailing semicolon first to avoid false positives on single statement terminator
        sql_stripped = sql.strip().rstrip(';')
        
        # Normalize spaces
        normalized = re.sub(r'\s+', ' ', sql_stripped).lower()
        
        # Block multi-statement queries
        if ';' in normalized:
            return False, "", "Multiple SQL statements separated by semicolons are strictly blocked."
            
        # Guarantee SELECT only
        if not normalized.startswith("select"):
            return False, "", "Only READ-ONLY queries starting with SELECT are allowed."
            
        # Strict write-keyword check
        blocked_keywords = {
            "insert", "update", "delete", "drop", "alter", "create", 
            "truncate", "grant", "revoke", "copy", "into", "replace", 
            "vacuum", "analyze", "explain"
        }
        for word in blocked_keywords:
            if re.search(rf'\b{word}\b', normalized):
                return False, "", f"Write operation keyword '{word}' is strictly prohibited."
                
        # Whitelist tables check
        table_matches = re.findall(r'\b(?:from|join)\s+([a-zA-Z0-9_\.]+)', normalized)
        
        if not table_matches:
            return False, "", "Unable to identify whitelisted tables in the query."
            
        for table in table_matches:
            table_name = table.split('.')[-1].strip('`"[]')
            if table_name not in self.TABLE_WHITELIST:
                return False, "", f"Table '{table_name}' is not in the whitelisted access list."
                
        if "limit" not in normalized:
            sql_stripped = sql_stripped + " LIMIT 100"
            
        return True, sql_stripped, ""


    def run_read_only_query(self, sql):
        """Executes a SQL query in a read-only transaction context."""
        is_valid, safe_sql, err = self.parse_and_validate_sql(sql)
        if not is_valid:
            return False, [], err
            
        conn = None
        cur = None
        try:
            conn = get_conn()
            conn.set_session(readonly=True, autocommit=False)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            cur.execute(safe_sql)
            rows = cur.fetchall()
            
            conn.rollback()
            cur.close(); conn.close()
            return True, [dict(r) for r in rows], ""
        except Exception as e:
            if cur:
                try: cur.close()
                except: pass
            if conn:
                try: 
                    conn.rollback()
                    conn.close()
                except: pass
            return False, [], f"Database query failed: {e}"

    def ask_database_question(self, user_question, config):
        schema_definition = """
        TimescaleDB Schema:
        
        1. Table: vehicles
           Columns: unique_id (varchar/IMEI, e.g. '868575043159851'), name, status ('active', 'inactive', 'draft'), company_name, driver_name, device_model, created_at, approval_date
        
        2. Table: live_vehicle_status
           Columns: imei (varchar), current_driver_name, current_driver_id (int), last_telemetry_id (bigint), last_timestamp (timestamp)
           
        3. Table: telemetry
           Columns: imei (varchar), timestamp (timestamp), longitude (double), latitude (double), speed (double), io_elements (jsonb or text)
           
        4. Table: trip_summary
           Columns: imei (varchar), start_time (timestamp), end_time (timestamp), distance_km (double), avg_speed (double), max_speed (double), duration_sec (int), fuel_consumed (double)
           
        5. Table: analytics_events
           Columns: imei (varchar), event_type (varchar, e.g. 'overspeed', 'harsh_driving', 'idle', 'trip_start', 'trip_end'), timestamp (timestamp), value (double, e.g. duration in seconds or speed)
           
        6. Table: drivers
           Columns: driver_id (int, primary key), name, rfid_tag
           
        7. Table: driver_sessions
           Columns: driver_id (int), imei (varchar), login_time (timestamp), logout_time (timestamp)
           
        8. Table: rfid_events
           Columns: imei (varchar), driver_id (int), timestamp (timestamp)
        """
        
        system_prompt = f"""
        You are a SQL Translation Engine. Convert natural language questions about fleet tracking into a single standard PostgreSQL/TimescaleDB SELECT query.
        
        Rules:
        - ONLY output the SQL query inside a markdown block: ```sql ... ```
        - Do not output explanations or text outside the block.
        - You must only SELECT from the schema tables whitelisted below.
        - Ensure calculations are safe: handle division by zero.
        - Enforce limits: maximum rows = 100.
        
        {schema_definition}
        """
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Translate to SQL: {user_question}"}
        ]
        
        success, sql_response, tokens = self.ask_ai(messages, config)
        if not success:
            return False, f"Could not generate query: {sql_response}", tokens
            
        sql_match = re.search(r'```sql\s*(.*?)\s*```', sql_response, re.DOTALL)
        if not sql_match:
            sql_match = re.search(r'```\s*(SELECT.*?)\s*```', sql_response, re.IGNORECASE | re.DOTALL)
            
        sql = sql_match.group(1) if sql_match else sql_response.strip()
        
        db_success, rows, db_err = self.run_read_only_query(sql)
        if not db_success:
            return False, f"SQL validation failed: {db_err}\nQuery generated: `{sql}`", tokens
            
        answer_formatter_prompt = f"""
        You are Antigravity, the IVMS AI Assistant. Answer the user's natural language question: "{user_question}".
        
        We queried the TimescaleDB database and got this data:
        Query executed: {sql}
        Results retrieved: {json.dumps(rows, default=str)}
        
        Analyze the data, perform calculations if needed, detect any highlights or anomalies, and explain it clearly in {config.get('language', 'en')}.
        If the results are empty, explain that gracefully.
        Present tabular outputs using standard markdown tables! Make the metrics stand out beautifully.
        """
        
        formatter_messages = [
            {"role": "system", "content": config.get("system_prompt", "")},
            {"role": "user", "content": answer_formatter_prompt}
        ]
        
        fmt_success, fmt_content, fmt_tokens = self.ask_ai(formatter_messages, config)
        return fmt_success, fmt_content, tokens + fmt_tokens

ai_service = AIService()
