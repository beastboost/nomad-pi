import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        try:
            page.on("pageerror", lambda exc: print(f"uncaught exception: {exc}"))

            import subprocess
            import time
            proc = subprocess.Popen(["python3", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8001"])
            time.sleep(5)

            await page.goto("http://127.0.0.1:8001")

            # Check for specific global function that should exist
            has_check_auth = await page.evaluate("typeof checkAuth !== 'undefined'")
            print(f"checkAuth exists: {has_check_auth}")

            await page.screenshot(path="final_verify.png")

            proc.terminate()
        except Exception as e:
            print(f"Error: {e}")
            if 'proc' in locals(): proc.terminate()

asyncio.run(run())
