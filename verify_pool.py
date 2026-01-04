import time
import threading
from app.database import get_db, return_db, set_setting, get_setting

def test_pool_exhaustion():
    print("Testing pool exhaustion prevention...")
    
    # The pool size is 5 in database.py
    # Let's try to get 10 connections in a row using the functions
    # If they correctly return connections, we should be fine.
    
    for i in range(20):
        set_setting(f"test_key_{i}", f"value_{i}")
        val = get_setting(f"test_key_{i}")
        if val != f"value_{i}":
            print(f"Error: Expected value_{i}, got {val}")
            return False
        if i % 5 == 0:
            print(f"Successfully performed {i} operations...")
            
    print("Sequential operations passed.")
    return True

def concurrent_op(id, results):
    try:
        for i in range(10):
            set_setting(f"thread_{id}_key_{i}", f"val_{i}")
            get_setting(f"thread_{id}_key_{i}")
        results[id] = True
    except Exception as e:
        print(f"Thread {id} failed: {e}")
        results[id] = False

def test_concurrent_pool_usage():
    print("\nTesting concurrent pool usage...")
    threads = []
    results = {}
    
    # Create 10 threads, each doing 10 operations
    # With pool size 5, this will definitely test the queueing/returning logic
    for i in range(10):
        t = threading.Thread(target=concurrent_op, args=(i, results))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    if all(results.values()):
        print("Concurrent operations passed.")
        return True
    else:
        print(f"Concurrent operations failed: {results}")
        return False

if __name__ == "__main__":
    success = test_pool_exhaustion()
    if success:
        success = test_concurrent_pool_usage()
        
    if success:
        print("\nAll pool tests passed!")
    else:
        print("\nPool tests FAILED!")
        exit(1)
