import os
import sys
import time

# Set environment variables for host-level connection conditionally
if "DB_HOST" not in os.environ:
    os.environ["DB_HOST"] = "127.0.0.1"
if "REDIS_HOST" not in os.environ:
    os.environ["REDIS_HOST"] = "127.0.0.1"

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.copilot_service import CopilotService
from ai_module.services.ai_service import ai_service

def run_test(query):
    print("=" * 60)
    print(f"USER QUERY: {query}")
    print("=" * 60)
    
    config = ai_service.load_config()
    
    # Process query
    res = CopilotService.process_chat_query(query, config)
    
    print(f"Detected Language: {res.get('language')}")
    print(f"Interaction Type: {res.get('type')}")
    print(f"Execution Time: {res.get('execution_time_ms'):.2f} ms")
    print("-" * 60)
    print("RESPONSE:")
    print(res.get("response"))
    print("=" * 60)
    print()

if __name__ == "__main__":
    print("Starting production AI Copilot verification tests...\n")
    
    # Test 1: Greetings (Conversational)
    run_test("hello there")
    time.sleep(10)
    
    # Test 2: Fleet status summary (DB Query)
    run_test("Show me active vehicles")
    time.sleep(10)
    
    # Test 3: Overspeeding query in Hindi (transliterated)
    run_test("kaun tej chala raha hai aaj?")
    time.sleep(10)
    
    # Test 4: Offline vehicles query in Arabic
    run_test("السيارات المتوقفة")
    time.sleep(10)
    
    # Test 5: Empty production data fallback (service tickets is empty table)
    run_test("are there any service tickets open?")
    
    print("Verification completed.")
