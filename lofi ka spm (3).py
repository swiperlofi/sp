import os
import sys
import time
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote

from playwright.async_api import async_playwright, Page, BrowserContext

# =========================
# CONFIG (runtime inputs)
# =========================
SESSION_ID = input("Session ID: ").strip()
DM_URL = input("Group Chat URL: ").strip()
MESSAGE = "speed match kr hakleeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee randceeeeeeeeeeeeee mdrcc"
THREADS = int(input("Threads (3–5): ") or 4)
MAX_MESSAGES = int(input("Max messages (0 = infinite): ") or 0)

# =========================
# TUNING (do not overdo)
# =========================
BASE_DELAY = 0.26       # fast but stable
BURST = 2               # micro-batch per loop
RECYCLE_AFTER = 120     # page refresh per thread
RECYCLE_COOLDOWN = 3.0  # seconds
ERROR_BACKOFF = 2.5     # seconds
VERIFY_SETTLE_MS = 140  # DOM settle after Enter

# =========================
# LOGGING
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# =========================
# STATS
# =========================
class Stats:
    def __init__(self):
        self.sent = 0
        self.failed = 0
        self.lock = asyncio.Lock()

    async def inc_sent(self, n=1):
        async with self.lock:
            self.sent += n

    async def inc_failed(self, n=1):
        async with self.lock:
            self.failed += n

STATS = Stats()

# =========================
# HELPERS
# =========================
async def prepare_context(pw) -> BrowserContext:
    browser = await pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"]
    )
    context = await browser.new_context(locale="en-US", viewport=None)
    await context.add_cookies([{
        "name": "sessionid",
        "value": unquote(SESSION_ID),
        "domain": ".instagram.com",
        "path": "/",
        "secure": True,
        "httpOnly": True,
        "sameSite": "None"
    }])
    return context

async def open_chat_page(context: BrowserContext) -> Page:
    page = await context.new_page()
    await page.goto(DM_URL, wait_until="domcontentloaded", timeout=120000)
    await page.wait_for_selector(
        'textarea[placeholder="Message..."], div[role="textbox"][contenteditable="true"]',
        timeout=120000
    )
    return page

async def send_once(page: Page) -> bool:
    box = page.locator(
        'textarea[placeholder="Message..."], div[role="textbox"][contenteditable="true"]'
    ).first
    await box.fill(MESSAGE)
    await box.press("Enter")
    await page.wait_for_timeout(VERIFY_SETTLE_MS)
    return True

# =========================
# WORKER
# =========================
async def worker(context: BrowserContext, tid: int):
    sent_local = 0
    page: Optional[Page] = None

    async def recycle():
        nonlocal page
        if page:
            await page.close()
        page = await open_chat_page(context)

    await recycle()

    while True:
        if MAX_MESSAGES and sent_local >= MAX_MESSAGES:
            break

        try:
            # micro-burst
            for _ in range(BURST):
                if MAX_MESSAGES and sent_local >= MAX_MESSAGES:
                    break

                ok = await send_once(page)
                if ok:
                    sent_local += 1
                    await STATS.inc_sent(1)
                else:
                    await STATS.inc_failed(1)

            # recycle guard
            if sent_local > 0 and sent_local % RECYCLE_AFTER == 0:
                await asyncio.sleep(RECYCLE_COOLDOWN)
                await recycle()

            await asyncio.sleep(BASE_DELAY)

        except Exception as e:
            logging.warning(f"Thread {tid} transient error; backing off")
            await STATS.inc_failed(1)
            await asyncio.sleep(ERROR_BACKOFF)

# =========================
# LIVE DASHBOARD
# =========================
async def dashboard(start_ts: float):
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        elapsed = max(1, int(time.time() - start_ts))
        rate = STATS.sent / elapsed
        print("INSTAGRAM DM SENDER — ULTRA (THREAD FAST)")
        print("-" * 44)
        print(f"Threads        : {THREADS}")
        print(f"Delay/Burst    : {BASE_DELAY}s / {BURST}")
        print(f"Recycle        : {RECYCLE_AFTER}")
        print(f"Sent           : {STATS.sent}")
        print(f"Failed         : {STATS.failed}")
        print(f"Avg rate       : {rate:.2f} msg/s")
        print("CTRL+C to stop")
        await asyncio.sleep(2)

# =========================
# MAIN
# =========================
async def main():
    start_ts = time.time()
    async with async_playwright() as pw:
        context = await prepare_context(pw)
        tasks = [
            asyncio.create_task(worker(context, i))
            for i in range(THREADS)
        ]
        tasks.append(asyncio.create_task(dashboard(start_ts)))
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())

