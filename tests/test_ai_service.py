from ai_module.services.ai_service import AIService

def test_sql_validation_with_trailing_semicolon():
    ai = AIService()
    
    # Test valid query with trailing semicolon
    query = """
    SELECT DISTINCT d.driver_id, d.name
    FROM drivers d
    WHERE d.driver_id IN (
        SELECT ds.driver_id FROM driver_sessions ds
        WHERE DATE(ds.login_time) = CURRENT_DATE
        UNION
        SELECT re.driver_id FROM rfid_events re
        WHERE DATE(re.timestamp) = CURRENT_DATE
        UNION
        SELECT lvs.current_driver_id
        FROM live_vehicle_status lvs
        WHERE DATE(lvs.last_timestamp) = CURRENT_DATE
    )
    LIMIT 100;
    """
    is_valid, sanitized_sql, error_message = ai.parse_and_validate_sql(query)
    assert is_valid, f"Failed to validate query: {error_message}"
    assert ";" not in sanitized_sql, "Sanitized SQL should not have a trailing semicolon"

def test_sql_validation_blocks_multi_statements():
    ai = AIService()
    
    # Test genuinely blocked multi-statement query
    query = "SELECT * FROM drivers; SELECT * FROM vehicles;"
    is_valid, sanitized_sql, error_message = ai.parse_and_validate_sql(query)
    assert not is_valid, "Should have blocked multi-statement query"
    assert "Multiple SQL statements" in error_message

def test_sql_validation_without_trailing_semicolon():
    ai = AIService()
    
    # Test valid query without trailing semicolon
    query = "SELECT * FROM drivers LIMIT 50"
    is_valid, sanitized_sql, error_message = ai.parse_and_validate_sql(query)
    assert is_valid, f"Failed to validate query: {error_message}"
