import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
import json

def run_tests():
    print("=== Initializing Test Client ===")
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        # Mock admin session transaction
        with client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['role'] = 'admin'
            sess['email'] = 'admin@ivms.com'
            
        print("\n--- Test 1: Anthropic Auto-Detection ---")
        payload = {
            "endpoint": "https://api.anthropic.com/v1",
            "api_key": "some_test_key"
        }
        res = client.post('/ai/config/fetch-models', json=payload)
        print(f"Status Code: {res.status_code}")
        data = res.get_json()
        print(f"Response: {data}")
        assert res.status_code == 200, "Should return 200 OK"
        assert "models" in data, "Should contain models list"
        assert "claude-opus-4-5" in data["models"], "Should contain Anthropic models"
        print("✅ Anthropic test passed successfully!")

        print("\n--- Test 2: OpenAI Key Invalid 401 Check ---")
        payload = {
            "endpoint": "https://api.openai.com/v1",
            "api_key": "sk-invalid-api-key-test-case"
        }
        res = client.post('/ai/config/fetch-models', json=payload)
        print(f"Status Code: {res.status_code}")
        data = res.get_json()
        print(f"Response: {data}")
        # Note: calling api.openai.com/v1/models with a completely invalid key will return 401
        assert res.status_code == 401, "Should return 401 Unauthorized"
        assert data.get("error") == "invalid_key", "Should return invalid_key error label"
        print("✅ OpenAI 401 check passed successfully!")

        print("\n--- Test 3: Bad Endpoint Connection Failure ---")
        payload = {
            "endpoint": "https://this-domain-does-not-exist-at-all-12345.com/v1",
            "api_key": "mock_key"
        }
        res = client.post('/ai/config/fetch-models', json=payload)
        print(f"Status Code: {res.status_code}")
        data = res.get_json()
        print(f"Response: {data}")
        assert res.status_code == 400, "Should return 400 Bad Request"
        assert data.get("error") == "connection_failed", "Should return connection_failed"
        print("✅ Connection failure check passed successfully!")

if __name__ == "__main__":
    try:
        run_tests()
        print("\n🎉 ALL TESTS PASSED SUCCESSFULLY! 🎉")
    except AssertionError as ae:
        print(f"\n❌ ASSERTION FAILED: {ae}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        sys.exit(1)
