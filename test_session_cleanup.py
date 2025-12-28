"""
Test script to verify session cleanup functionality.
"""
import os
import sys
import time
import sqlite3
from datetime import datetime, timedelta

# Add app to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import database

def setup_test_db():
    """Create a test database with some sessions."""
    # Use a test database
    original_db = database.DB_PATH
    database.DB_PATH = "data/test_nomad.db"
    
    # Clean up if exists
    if os.path.exists(database.DB_PATH):
        os.remove(database.DB_PATH)
    
    # Initialize
    database.init_db()
    
    return original_db

def teardown_test_db(original_db):
    """Clean up test database."""
    if os.path.exists(database.DB_PATH):
        os.remove(database.DB_PATH)
    database.DB_PATH = original_db

def test_session_cleanup():
    """Test that session cleanup works correctly."""
    print("Testing session cleanup functionality...")
    
    original_db = setup_test_db()
    
    try:
        # Create some test sessions
        print("\n1. Creating test sessions...")
        database.create_session("valid_token_1")
        database.create_session("valid_token_2")
        
        # Create an expired session by directly manipulating the database
        conn = database.get_db()
        c = conn.cursor()
        expired_date = (datetime.now() - timedelta(days=31)).isoformat()
        c.execute('''
            INSERT INTO sessions (token, created_at)
            VALUES (?, ?)
        ''', ("expired_token", expired_date))
        conn.commit()
        conn.close()
        
        # Verify all sessions exist
        conn = database.get_db()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) as cnt FROM sessions')
        count = c.fetchone()['cnt']
        conn.close()
        print(f"   Total sessions before cleanup: {count}")
        assert count == 3, f"Expected 3 sessions, got {count}"
        
        # Test get_session doesn't trigger cleanup (bug fix verification)
        print("\n2. Testing get_session doesn't trigger cleanup...")
        session = database.get_session("valid_token_1")
        assert session is not None, "Valid session should be found"
        
        # Verify expired session still exists (proving cleanup wasn't called)
        conn = database.get_db()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) as cnt FROM sessions WHERE token = ?', ("expired_token",))
        count = c.fetchone()['cnt']
        conn.close()
        print(f"   Expired session still exists: {count == 1}")
        assert count == 1, "Expired session should still exist (cleanup not called)"
        
        # Test explicit cleanup
        print("\n3. Testing explicit cleanup_sessions()...")
        database.cleanup_sessions()
        
        # Verify expired session is removed
        conn = database.get_db()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) as cnt FROM sessions')
        total = c.fetchone()['cnt']
        c.execute('SELECT COUNT(*) as cnt FROM sessions WHERE token = ?', ("expired_token",))
        expired = c.fetchone()['cnt']
        conn.close()
        
        print(f"   Total sessions after cleanup: {total}")
        print(f"   Expired session exists: {expired == 1}")
        assert total == 2, f"Expected 2 sessions after cleanup, got {total}"
        assert expired == 0, "Expired session should be removed"
        
        # Test that valid sessions still work
        print("\n4. Testing valid sessions still work...")
        session1 = database.get_session("valid_token_1")
        session2 = database.get_session("valid_token_2")
        assert session1 is not None, "Valid session 1 should still work"
        assert session2 is not None, "Valid session 2 should still work"
        
        # Test that expired token returns None
        print("\n5. Testing expired token returns None...")
        expired_session = database.get_session("expired_token")
        assert expired_session is None, "Expired token should return None"
        
        print("\n✅ All tests passed!")
        return True
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        teardown_test_db(original_db)

if __name__ == "__main__":
    success = test_session_cleanup()
    sys.exit(0 if success else 1)
