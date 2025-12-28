"""
Test script to verify bug fixes for upload speed, JSON errors, and audio issues.
"""
import os
import sys
import json

# Add app to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_upload_chunk_size():
    """Test that upload chunk size has been increased."""
    print("Testing upload chunk size...")
    from app.routers import uploads
    
    # Check that CHUNK_SIZE is now 8MB instead of 1MB
    expected_size = 8 * 1024 * 1024
    actual_size = uploads.CHUNK_SIZE
    
    print(f"   Expected chunk size: {expected_size / 1024 / 1024}MB")
    print(f"   Actual chunk size: {actual_size / 1024 / 1024}MB")
    
    assert actual_size == expected_size, f"Chunk size should be {expected_size}, got {actual_size}"
    print("   ✅ Upload chunk size correctly increased to 8MB")
    return True

def test_browse_json_serialization():
    """Test that browse endpoint returns properly serializable JSON."""
    print("\nTesting browse endpoint JSON serialization...")
    
    # Create a test directory structure
    test_dir = "data/test_browse"
    os.makedirs(test_dir, exist_ok=True)
    
    # Create a test file
    test_file = os.path.join(test_dir, "test.txt")
    with open(test_file, "w") as f:
        f.write("test content")
    
    try:
        from app.routers import media
        
        # Test the browse function
        result = media.browse_files(path="/data/test_browse")
        
        print(f"   Browse result keys: {result.keys()}")
        print(f"   Number of items: {len(result.get('items', []))}")
        
        # Verify JSON serialization
        json_str = json.dumps(result)
        print(f"   JSON serialization successful: {len(json_str)} bytes")
        
        # Verify all items have correct types
        for item in result.get('items', []):
            assert isinstance(item['name'], str), f"name should be str, got {type(item['name'])}"
            assert isinstance(item['path'], str), f"path should be str, got {type(item['path'])}"
            assert isinstance(item['is_dir'], bool), f"is_dir should be bool, got {type(item['is_dir'])}"
            assert isinstance(item['size'], int), f"size should be int, got {type(item['size'])}"
            print(f"   Item: {item['name']} - size: {item['size']} (type: {type(item['size']).__name__})")
        
        print("   ✅ Browse endpoint returns properly typed JSON")
        return True
        
    finally:
        # Cleanup
        if os.path.exists(test_file):
            os.remove(test_file)
        if os.path.exists(test_dir):
            os.rmdir(test_dir)

def test_video_preload_setting():
    """Test that video element uses proper preload setting."""
    print("\nTesting video preload setting...")
    
    # Read the JavaScript file
    js_file = "app/static/js/app.js"
    if not os.path.exists(js_file):
        print("   ⚠️  JavaScript file not found, skipping test")
        return True
    
    with open(js_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for the preload setting
    if "video.preload = 'auto'" in content:
        print("   ✅ Video preload set to 'auto' for better audio loading")
    else:
        print("   ❌ Video preload not set to 'auto'")
        return False
    
    # Check for crossOrigin setting
    if "video.crossOrigin = 'anonymous'" in content:
        print("   ✅ Video crossOrigin set for better compatibility")
    else:
        print("   ⚠️  Video crossOrigin not set (optional)")
    
    return True

def test_logger_import():
    """Test that logger is properly imported in media router."""
    print("\nTesting logger import...")
    from app.routers import media
    
    assert hasattr(media, 'logger'), "Logger should be imported"
    print("   ✅ Logger properly imported in media router")
    return True

def test_platform_import():
    """Test that platform module is properly imported."""
    print("\nTesting platform import...")
    from app.routers import media
    
    # Check if platform is available in the module
    import inspect
    source = inspect.getsource(media)
    assert 'import platform' in source, "Platform module should be imported"
    print("   ✅ Platform module properly imported")
    return True

def run_all_tests():
    """Run all tests and report results."""
    print("=" * 60)
    print("Running Bug Fix Tests")
    print("=" * 60)
    
    tests = [
        ("Upload Chunk Size", test_upload_chunk_size),
        ("Browse JSON Serialization", test_browse_json_serialization),
        ("Video Preload Setting", test_video_preload_setting),
        ("Logger Import", test_logger_import),
        ("Platform Import", test_platform_import),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"   ❌ Test failed with error: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    return passed == total

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
