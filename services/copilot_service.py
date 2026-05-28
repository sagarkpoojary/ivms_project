import time
import json
import re
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from models.database import get_conn
from ai_module.services.ai_service import ai_service

# Global cache for database query responses to minimize TimescaleDB and Groq load
# Structure: (intent, language) -> (timestamp, formatted_response)
_QUERY_CACHE = {}
_CACHE_TTL = 10  # Cache TTL in seconds

# Context memory for short operational continuity (expires after 60 seconds)
_CONTEXT_MEMORY = {}
_CONTEXT_MEMORY_TTL = 60

# Operational response templates for compact formatting
OPERATIONAL_TEMPLATES = {
    "offline_vehicles": {
        "en": "{count} vehicles currently offline.\nLatest updates:\n{items}",
        "ar": "{count} مركبات متوقفة حالياً.\nآخر التحديثات:\n{items}",
        "hi": "वर्तमान में {count} गाड़ियाँ ऑफलाइन हैं।\nआधिक बतरी हों:\n{items}"
    },
    "active_drivers": {
        "en": "{count} active drivers detected.\nCurrently driving:\n{items}",
        "ar": "{count} سواق نشطون مكتشفون.\nيقودون حالياً:\n{items}",
        "hi": "{count} सक्रिय ड्राइवर पाया गया है।\nवर्तमान में ड्राइव कर रहे:\n{items}"
    }
}

# Enhanced multilingual keyword mapping for intent detection
INTENT_KEYWORDS = {
    "offline_vehicles": {
        "en": ["offline", "stopped", "disconnected", "متوقف", "ऑफलाइन"],
        "ar": ["متوقف", "مقفل", "غير متصل", "توقف", "ميت"],
        "hi": ["ऑफलाइन", "बंद", "रुका", "न चल रही", "तैरा"]
    },
    "active_vehicles": {
        "en": ["active", "moving", "running", "shaghal", "चल रही", "चल रहा"],
        "ar": ["شغال", "نشط", "قيد التشغيل", "في الحركة", "شغالة"],
        "hi": ["चल रही", "चल रहा", "सक्रिय", "सम movement", "चलाकotlin"]
    },
    "overspeeding": {
        "en": ["speed", "fast", "overspeed", "speeding", "سرع", "तेज"],
        "ar": ["السرعة", "سرع", "تجاوز الحد", "سريع"],
        "hi": ["गति", "तेज", "तेज़", "भीड़"]
    },
    "idle_vehicles": {
        "en": ["idle", "standing", "waiting", "jam", "خمول", "अटका"],
        "ar": ["خمول", "وقف", "يتوقف", "متوقف مؤقتا"],
        "hi": ["आ�इडल", "थिर குறை", "थामा"]
    },
    "fleet_summary": {
        "en": ["fleet", "summary", "overview", "ملخص", "गाड़ी"],
        "ar": ["ملخص", "أسطول", "نظرة عامة"],
        "hi": ["फ़्लीट", "सारांश", "गाड़ी"]
    }
}

# Pre-defined safe parameterized SQL queries for each intent
INTENT_QUERIES = {
    "fleet_summary": """
        SELECT 
            COUNT(*) as total_vehicles,
            SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) as online_vehicles,
            SUM(CASE WHEN status = 'offline' THEN 1 ELSE 0 END) as offline_vehicles,
            SUM(CASE WHEN ignition = TRUE AND speed > 0 AND status = 'online' THEN 1 ELSE 0 END) as moving_vehicles,
            SUM(CASE WHEN ignition = TRUE AND COALESCE(speed, 0) <= 2 AND status = 'online' THEN 1 ELSE 0 END) as idling_vehicles,
            SUM(CASE WHEN status = 'ignition_off' THEN 1 ELSE 0 END) as ignition_off_vehicles
        FROM live_vehicle_status
    """,
    "active_vehicles": """
        SELECT v.name as vehicle_name, l.imei, l.speed, l.ignition, l.status, l.current_driver_name as driver_name
        FROM live_vehicle_status l
        JOIN vehicles v ON l.imei = v.unique_id
        WHERE l.status IN ('moving', 'idle') OR l.ignition = TRUE OR l.speed > 0
        ORDER BY l.speed DESC
        LIMIT 50
    """,
    "offline_vehicles": """
        SELECT v.name as vehicle_name, l.imei, l.last_timestamp, l.packet_age_seconds
        FROM live_vehicle_status l
        JOIN vehicles v ON l.imei = v.unique_id
        WHERE l.status = 'offline'
        ORDER BY l.last_timestamp DESC NULLS LAST
        LIMIT 50
    """,
    "idle_vehicles": """
        SELECT v.name as vehicle_name, l.imei, l.last_timestamp, l.current_driver_name as driver_name
        FROM live_vehicle_status l
        JOIN vehicles v ON l.imei = v.unique_id
        WHERE l.status = 'idle'
        LIMIT 50
    """,
    "overspeeding": """
        SELECT v.name as vehicle_name, ae.imei, ae.timestamp, ae.value as speed, COALESCE(l.current_driver_name, 'Unknown') as driver_name
        FROM analytics_events ae
        JOIN vehicles v ON ae.imei = v.unique_id
        LEFT JOIN live_vehicle_status l ON ae.imei = l.imei
        WHERE ae.event_type = 'overspeed' AND ae.timestamp >= CURRENT_DATE - INTERVAL '3 days'
        ORDER BY ae.timestamp DESC, ae.value DESC
        LIMIT 50
    """,
    "trip_counts": """
        SELECT v.name as vehicle_name, count(*) as trip_count, ROUND(sum(ts.distance_km)::numeric, 2) as total_distance_km
        FROM trip_summary ts
        JOIN vehicles v ON ts.imei = v.unique_id
        WHERE ts.start_time >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY v.name
        ORDER BY trip_count DESC
        LIMIT 50
    """,
    "active_drivers": """
        SELECT DISTINCT COALESCE(l.current_driver_name, d.name) as driver_name, v.name as vehicle_name, l.imei
        FROM live_vehicle_status l
        JOIN vehicles v ON l.imei = v.unique_id
        LEFT JOIN drivers d ON l.current_driver_id = d.driver_id
        WHERE l.current_driver_name IS NOT NULL AND l.current_driver_name NOT IN ('No Driver', 'Unknown Tag', '')
        LIMIT 50
    """,
    "attendance": """
        SELECT d.name as driver_name, da.date, da.first_checkin, da.last_checkout, da.total_hours
        FROM driver_attendance da
        JOIN drivers d ON da.driver_id = d.driver_id
        ORDER BY da.date DESC, da.first_checkin DESC
        LIMIT 50
    """,
    "maintenance_due": """
        SELECT v.name as vehicle_name, ms.service_type, ms.description, ms.target_date, ms.target_mileage, ms.status
        FROM maintenance_schedule ms
        JOIN vehicles v ON ms.imei = v.unique_id
        WHERE ms.status = 'pending' OR ms.target_date >= CURRENT_DATE
        ORDER BY ms.target_date ASC
        LIMIT 50
    """,
    "service_tickets": """
        SELECT st.id, st.title, st.category, st.priority, st.status, st.assigned_to, st.created_at
        FROM service_tickets st
        ORDER BY st.created_at DESC
        LIMIT 50
    """,
    "site_visits": """
        SELECT sv.scheduled_time, sv.arrival_time, sv.status, v.name as vehicle_name, sv.work_report
        FROM site_visits sv
        LEFT JOIN vehicles v ON sv.imei = v.unique_id
        ORDER BY sv.scheduled_time DESC
        LIMIT 50
    """,
    "ignition_status": """
        SELECT v.name as vehicle_name, l.ignition, l.status, l.current_driver_name as driver_name
        FROM live_vehicle_status l
        JOIN vehicles v ON l.imei = v.unique_id
        ORDER BY l.ignition DESC
        LIMIT 50
    """
}

# Standard translations for "No real production data found" guardrail response
GUARDRAIL_RESPONSES = {
    "en": "No real production data found.",
    "ar": "لم يتم العثور على بيانات إنتاجية حقيقية.",
    "hi": "कोई वास्तविक प्रोडक्शन डेटा नहीं मिला।"
}


class CopilotService:
    @staticmethod
    def run_safe_query(sql: str, params: tuple = None) -> tuple:
        """Executes a safe read-only SQL query with a 5-second statement timeout."""
        conn = None
        cur = None
        try:
            conn = get_conn()
            conn.set_session(readonly=True, autocommit=False)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # Set strict execution timeout to protect TimescaleDB
            cur.execute("SET statement_timeout = 5000")
            cur.execute(sql, params or ())
            rows = cur.fetchall()
            conn.rollback()
            return True, [dict(r) for r in rows]
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
            return False, str(e)
        finally:
            if cur:
                try:
                    cur.close()
                except:
                    pass
            if conn:
                try:
                    conn.close()
                except:
                    pass

    @staticmethod
    def detect_intent_and_language(query: str, config: dict) -> dict:
        """Uses LLM in structured mode to detect intent, language, and parameters from user query."""
        system_prompt = """
        You are the Intent and Language Classifier for IVMS (Intelligent Vehicle Monitoring System).
        Analyze the user's query and output ONLY a raw JSON block. Do not include markdown wraps (like ```json), explanations, or stray characters.
        
        You must classify the user's intent into one of the following exact categories:
        - "fleet_summary" (overview of vehicle counts, moving, offline)
        - "active_vehicles" (vehicles currently running, moving, or active)
        - "offline_vehicles" (vehicles currently offline or disconnected)
        - "idle_vehicles" (idling anomalies, vehicles standing still with engine on)
        - "overspeeding" (who is speeding, fast drivers, overspeed events)
        - "trip_counts" (trips, distances driven, trip summary)
        - "active_drivers" (who drives today, logged-in drivers)
        - "attendance" (driver attendance, work checkins)
        - "maintenance_due" (maintenance scheduled, services due)
        - "service_tickets" (open support tickets, customer service issues)
        - "site_visits" (technician visits to client locations, site activities)
        - "ignition_status" (ignition states of vehicles)
        - "conversational" (general conversation, greetings, capabilities, support questions)

        You must detect the user's input language as either:
        - "en" (English)
        - "ar" (Arabic / العربية)
        - "hi" (Hindi / हिन्दी or transliterated Hinglish)

        JSON Schema output:
        {
          "intent": "exact_intent_name",
          "language": "en" | "ar" | "hi",
          "params": {}
        }
        """
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Query: {query}"}
        ]
        
        success, response_text, tokens = ai_service.ask_ai(messages, config)
        if not success:
            return {"intent": "conversational", "language": config.get("language", "en"), "params": {}}
        
        # Parse JSON output robustly
        try:
            # Clean possible markdown wrap ```json
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
                cleaned = re.sub(r'\s*```$', '', cleaned)
            parsed = json.loads(cleaned)
            return parsed
        except Exception:
            # Safe rule-based keyword fallback if JSON parsing fails
            query_lower = query.lower()
            detected_lang = "en"
            if any(char in query for char in ["أ", "إ", "ش", "ي", "ر", "ة", "؟"]):
                detected_lang = "ar"
            elif any(char in query for char in ["क", "ग", "ा", "ी", "ॉ"]):
                detected_lang = "hi"
            
            # Enhanced keyword-based intent mapper using INTENT_KEYWORDS
            intent = "conversational"
            for intent_name, keywords_dict in INTENT_KEYWORDS.items():
                all_keywords = keywords_dict.get("en", []) + keywords_dict.get(detected_lang, [])
                if any(kw in query_lower for kw in [k.lower() for k in all_keywords]):
                    intent = intent_name
                    break
            
            return {"intent": intent, "language": detected_lang, "params": {}}
    
    @staticmethod
    def _resolve_contextual_query(query: str, language: str) -> str:
        """Resolve follow-up queries referencing previous context (e.g., 'recently?', 'which one?')."""
        query_lower = query.lower().strip()
        contextual_keywords = {
            "en": ["recent", "recently", "latest", "last", "which one", "who", "what", "when"],
            "ar": ["الأخيرة", "أي واحدة", "متى", "الأخير", "حديثا"],
            "hi": ["अंतिम", "कौन सा", "कब", "भेजा"]
        }
        keywords = contextual_keywords.get(language, contextual_keywords["en"])
        
        if any(kw in query_lower for kw in keywords):
            # Check context memory for recent intent
            context_key = f"context_{language}"
            ctx = _CONTEXT_MEMORY.get(context_key)
            if ctx and time.time() - ctx.get("ts", 0) < _CONTEXT_MEMORY_TTL:
                # Return the contextual intent based on trigger words
                if "recent" in query_lower or "recently" in query_lower or "latest" in query_lower:
                    return "offline_vehicles"  # Default to offline vehicles for recency
        return None
    
    @staticmethod
    def _format_operational_response(intent: str, rows: list, language: str) -> str:
        """Format database results in operational compact style."""
        if intent == "offline_vehicles" and rows:
            count = len(rows)
            items = []
            for r in rows[:5]:  # Limit to 5 for compact display
                name = r.get('vehicle_name') or 'Unknown'
                ts = r.get('last_timestamp')
                if ts:
                    ts_str = ts.strftime('%H:%M') if hasattr(ts, 'strftime') else str(ts).split('T')[1][:5]
                    items.append(f"• {name} — {ts_str}")
                else:
                    items.append(f"• {name}")
            template = OPERATIONAL_TEMPLATES.get(intent, {}).get(language, "{count} vehicles offline.\n{items}")
            return template.format(count=count, items="\n".join(items))
        elif intent == "active_drivers" and rows:
            count = len(rows)
            items = []
            for r in rows[:5]:
                driver = r.get('driver_name') or 'Unknown'
                vehicle = r.get('vehicle_name') or 'Unassigned'
                items.append(f"• {driver} → {vehicle}")
            template = OPERATIONAL_TEMPLATES.get(intent, {}).get(language, "{count} active drivers.\n{items}")
            return template.format(count=count, items="\n".join(items))
        return GUARDRAIL_RESPONSES.get(language, GUARDRAIL_RESPONSES["en"])
    
    @classmethod
    def process_chat_query(cls, user_message: str, config: dict, context: str = "") -> dict:
        """Autoruns intent matching, executes pre-compiled SQL queries with parameters, and formats replies."""
        start_time = time.time()
        
        # 1. Detect Intent and Language
        classification = cls.detect_intent_and_language(user_message, config)
        intent = classification.get("intent", "conversational")
        language = classification.get("language", "en")
        
        # Guardrail normalization
        if language not in GUARDRAIL_RESPONSES:
            language = "en"
        
        # Check cache for database query intents
        cache_key = (intent, language)
        if intent != "conversational" and cache_key in _QUERY_CACHE:
            cached_ts, cached_response = _QUERY_CACHE[cache_key]
            if time.time() - cached_ts < _CACHE_TTL:
                execution_time = (time.time() - start_time) * 1000
                ai_service.add_log(user_message, cached_response, f"DB Query ({intent} - CACHED)", "Success", 0)
                return {
                    "response": cached_response,
                    "type": "DB Query",
                    "language": language,
                    "execution_time_ms": execution_time
                }
        
        # 2. Intent Handling
        if intent == "conversational":
            # Check for contextual follow-up queries (e.g., "which one recently?")
            context_key = f"context_{language}"
            contextual_ref = cls._resolve_contextual_query(user_message, language)
            if contextual_ref:
                intent = contextual_ref
                sql = INTENT_QUERIES.get(intent)
                if sql:
                    success, rows = cls.run_safe_query(sql)
                    if success and rows:
                        # Format using operational style
                        formatted = cls._format_operational_response(intent, rows, language)
                        execution_time = (time.time() - start_time) * 1000
                        ai_service.add_log(user_message, formatted, f"DB Query ({intent} - Contextual)", "Success", 0)
                        return {
                            "response": formatted,
                            "type": "DB Query",
                            "language": language,
                            "execution_time_ms": execution_time
                        }
            
            # Conversational flow with strict guardrails
            system_prompt = f"""You are the IVMS Copilot, an operational fleet intelligence assistant powered by aitsun.ai.
            Reply in {language} only. Response format: maximum 2 sentences. No placeholders.
            Use telemetry-aware tone. Never ask "how can I help". Never list capabilities.
            Brand footer required: "IVMS Copilot — Powered by aitsun.ai"
            """
            
            prompt_content = user_message
            if context:
                prompt_content = f"Context: {context}\n\nUser: {user_message}"
                
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_content}
            ]
            success, response_text, tokens = ai_service.ask_ai(messages, config)
            execution_time = (time.time() - start_time) * 1000
            
            if success:
                # Store context for follow-up
                _CONTEXT_MEMORY[context_key] = {"intent": "conversational", "ts": time.time()}
                ai_service.add_log(user_message, response_text, "Conversational", "Success", tokens)
                return {
                    "response": response_text,
                    "type": "Conversational",
                    "language": language,
                    "execution_time_ms": execution_time
                }
            else:
                ai_service.add_log(user_message, "Connection failed", "Conversational", "Error", 0, error=response_text)
                return {
                    "response": "IVMS Copilot unavailable. Check connection.",
                    "type": "Conversational",
                    "language": language,
                    "execution_time_ms": execution_time
                }
                
        # 3. Database Query Intent
        sql = INTENT_QUERIES.get(intent)
        if not sql:
            # Fallback for unsupported intents
            response_text = GUARDRAIL_RESPONSES[language]
            execution_time = (time.time() - start_time) * 1000
            ai_service.add_log(user_message, response_text, "DB Query Fallback", "Success", 0)
            return {
                "response": response_text,
                "type": "DB Query",
                "language": language,
                "execution_time_ms": execution_time
            }
            
        # Run safe database query
        success, rows = cls.run_safe_query(sql)
        
        # 4. Handle Guardrails and Formatter
        if not success or not rows:
            # Database returned empty: Respond honestly without hallucinating
            response_text = GUARDRAIL_RESPONSES[language]
            execution_time = (time.time() - start_time) * 1000
            ai_service.add_log(user_message, response_text, f"DB Query ({intent} - Empty)", "Success", 0, error="" if success else rows)
            
            # Cache the empty response
            _QUERY_CACHE[cache_key] = (time.time(), response_text)
            
            return {
                "response": response_text,
                "type": "DB Query",
                "language": language,
                "execution_time_ms": execution_time
            }
            
        # Format database rows using LLM
        formatter_system = f"""
        You are the IVMS Copilot, the IVMS fleet intelligence assistant powered by aitsun.ai.
        Explain the database results clearly and professionally in the requested language: {language}.
        
        CRITICAL RULES:
        - Use standard markdown tables to present metrics elegantly.
        - Highlight key figures, active indicators, or anomalous values.
        - NEVER fabricate or make up any records, vehicle names, or driver names that are not in the query results.
        - If Arabic (ar), preserve standard right-to-left layout by structuring sentences cleanly.
        - Preserve the branding tagline at the very bottom in a separate line: "IVMS Copilot — Powered by aitsun.ai".
        """
        
        data_payload = {
            "User Question": user_message,
            "Intent": intent,
            "ResultsCount": len(rows),
            "Results": rows
        }
        
        messages = [
            {"role": "system", "content": formatter_system},
            {"role": "user", "content": f"Database output to format:\n{json.dumps(data_payload, default=str)}"}
        ]
        
        fmt_success, formatted_text, fmt_tokens = ai_service.ask_ai(messages, config)
        execution_time = (time.time() - start_time) * 1000
        
        if fmt_success:
            # Cache the successful formatted response
            _QUERY_CACHE[cache_key] = (time.time(), formatted_text)
            
            ai_service.add_log(user_message, formatted_text, f"DB Query ({intent})", "Success", fmt_tokens)
            return {
                "response": formatted_text,
                "type": "DB Query",
                "language": language,
                "execution_time_ms": execution_time
            }
        else:
            fallback_text = GUARDRAIL_RESPONSES[language]
            ai_service.add_log(user_message, fallback_text, f"DB Query ({intent} - Format Error)", "Success", 0, error=formatted_text)
            return {
                "response": fallback_text,
                "type": "DB Query",
                "language": language,
                "execution_time_ms": execution_time
            }
