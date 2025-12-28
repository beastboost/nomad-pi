"""
Test script to verify show organization with OMDB integration.
"""
import os
import sys
import re

# Add app to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_organize_shows_signature():
    """Test that organize_shows has the correct parameters."""
    print("Testing organize_shows function signature...")
    
    # Read the media.py file
    media_file = "app/routers/media.py"
    with open(media_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the organize_shows function definition
    pattern = r'def organize_shows\((.*?)\):'
    match = re.search(pattern, content, re.DOTALL)
    
    if not match:
        print("   ❌ Could not find organize_shows function")
        return False
    
    params = match.group(1)
    print(f"   Function parameters: {params[:100]}...")
    
    # Check for required parameters
    required_params = ['dry_run', 'rename_files', 'use_omdb', 'write_poster', 'limit']
    for param in required_params:
        if param in params:
            print(f"   ✅ Parameter '{param}' found")
        else:
            print(f"   ❌ Parameter '{param}' missing")
            return False
    
    return True

def test_omdb_integration():
    """Test that organize_shows includes OMDB integration."""
    print("\nTesting OMDB integration in organize_shows...")
    
    media_file = "app/routers/media.py"
    with open(media_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the organize_shows function
    pattern = r'def organize_shows\(.*?\):(.*?)(?=\n@router|def \w+\(|$)'
    match = re.search(pattern, content, re.DOTALL)
    
    if not match:
        print("   ❌ Could not find organize_shows function body")
        return False
    
    function_body = match.group(1)
    
    # Check for OMDB-related code
    checks = [
        ('omdb_fetch', 'OMDB fetch call'),
        ('cache_remote_poster', 'Poster caching'),
        ('shows_processed', 'Show tracking'),
        ('media_type="series"', 'Series media type'),
        ('poster.jpg', 'Poster file saving'),
    ]
    
    for check_str, description in checks:
        if check_str in function_body:
            print(f"   ✅ {description} found")
        else:
            print(f"   ❌ {description} missing")
            return False
    
    return True

def test_frontend_integration():
    """Test that frontend calls organize_shows with OMDB parameters."""
    print("\nTesting frontend integration...")
    
    js_file = "app/static/js/app.js"
    if not os.path.exists(js_file):
        print("   ⚠️  JavaScript file not found, skipping test")
        return True
    
    with open(js_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the organizeShows function
    pattern = r'async function organizeShows\(.*?\)\s*\{(.*?)\n\}'
    match = re.search(pattern, content, re.DOTALL)
    
    if not match:
        print("   ❌ Could not find organizeShows function")
        return False
    
    function_body = match.group(1)
    
    # Check for OMDB parameters in the fetch call
    if 'use_omdb=1' in function_body and 'write_poster=1' in function_body:
        print("   ✅ Frontend calls organize_shows with use_omdb=1&write_poster=1")
    else:
        print("   ❌ Frontend missing OMDB parameters")
        return False
    
    # Check for shows_metadata_fetched display
    if 'shows_metadata_fetched' in function_body:
        print("   ✅ Frontend displays metadata fetch count")
    else:
        print("   ⚠️  Frontend doesn't display metadata fetch count (optional)")
    
    return True

def test_auto_organize_integration():
    """Test that auto-organize uses OMDB for shows."""
    print("\nTesting auto-organize integration...")
    
    media_file = "app/routers/media.py"
    with open(media_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the auto-organize code in maybe_start_index_build
    pattern = r'if category == "shows":(.*?)else:'
    match = re.search(pattern, content, re.DOTALL)
    
    if not match:
        print("   ❌ Could not find auto-organize code for shows")
        return False
    
    auto_organize_code = match.group(1)
    
    if 'use_omdb=True' in auto_organize_code and 'write_poster=True' in auto_organize_code:
        print("   ✅ Auto-organize uses OMDB for shows")
    else:
        print("   ❌ Auto-organize missing OMDB parameters for shows")
        return False
    
    return True

def test_return_value():
    """Test that organize_shows returns metadata fetch count."""
    print("\nTesting return value...")
    
    media_file = "app/routers/media.py"
    with open(media_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the return statement in organize_shows
    pattern = r'def organize_shows\(.*?\):(.*?)return \{(.*?)\}'
    match = re.search(pattern, content, re.DOTALL)
    
    if not match:
        print("   ❌ Could not find return statement")
        return False
    
    return_dict = match.group(2)
    
    required_keys = ['status', 'dry_run', 'rename_files', 'use_omdb', 'write_poster', 
                     'moved', 'skipped', 'errors', 'shows_metadata_fetched', 'planned']
    
    for key in required_keys:
        if f'"{key}"' in return_dict or f"'{key}'" in return_dict:
            print(f"   ✅ Return includes '{key}'")
        else:
            print(f"   ❌ Return missing '{key}'")
            return False
    
    return True

def run_all_tests():
    """Run all tests and report results."""
    print("=" * 60)
    print("Testing Show Organization with OMDB Integration")
    print("=" * 60)
    
    tests = [
        ("Function Signature", test_organize_shows_signature),
        ("OMDB Integration", test_omdb_integration),
        ("Frontend Integration", test_frontend_integration),
        ("Auto-Organize Integration", test_auto_organize_integration),
        ("Return Value", test_return_value),
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
