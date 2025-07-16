import asyncio
import logging
import os
import json

import asyncpg
from playwright.async_api import async_playwright

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://workers:secret@db:5432/workersdb")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/bot.log")
    ],
)

BUTTONS = [
    "Быть участником канала (Награда: 0.1 USD)",
    "Быть подписанным на канал (Награда: 0.1 USD)",
    "Подписаться на канал (Награда: 0.1 USD)",
    "Подписка на канал (Награда: 0.1 USD)",
]

CHECK_BUTTON = "Проверить"
BACK_BUTTON = "Вернуться назад"
START_COMMAND = "/start"
TASKS_BUTTON = "Задания"

RETRY_DELAY = 300  # 5 минут

async def get_referral_and_sessions(conn):
    # Находит активную рефералку с незанятыми сессиями
    rows = await conn.fetch("""
        SELECT r.id, r.url, r.max_sessions,
            COUNT(s.id) FILTER (WHERE s.status = 'used' AND s.reserved_for_referral_id = r.id) as used_sessions,
            COUNT(s.id) FILTER (WHERE s.status = 'active' AND s.reserved_for_referral_id = r.id) as reserved_sessions
        FROM referral_links r
        LEFT JOIN sessions s ON s.reserved_for_referral_id = r.id
        WHERE r.status = 'actual'
        GROUP BY r.id
        HAVING COUNT(s.id) FILTER (WHERE s.status = 'used' AND s.reserved_for_referral_id = r.id) < r.max_sessions
        ORDER BY r.id
        LIMIT 1
    """)

    if not rows:
        return None, []

    ref = rows[0]

    # Сколько сессий надо забронировать?
    needed = ref['max_sessions'] - ref['used_sessions'] - ref['reserved_sessions']
    if needed <= 0:
        return None, []

    # Забронировать сессии для этой реферальной ссылки
    sessions = await conn.fetch("""
        UPDATE sessions SET reserved_for_referral_id = $1
        WHERE id IN (
            SELECT id FROM sessions
            WHERE status = 'active' AND reserved_for_referral_id IS NULL
            LIMIT $2
            FOR UPDATE SKIP LOCKED
        )
        RETURNING *
    """, ref['id'], needed)

    return ref, sessions

async def mark_session_used(conn, session_id):
    await conn.execute("""
        UPDATE sessions SET status='used', reserved_for_referral_id=NULL WHERE id=$1
    """, session_id)

async def click_button_by_text(page, text):
    try:
        btn = await page.wait_for_selector(f'text="{text}"', timeout=7000)
        await btn.click()
        logging.info(f"Clicked button '{text}'")
        await page.wait_for_timeout(1500)
    except Exception as e:
        logging.error(f"Button '{text}' not found or click failed: {e}")
        raise

async def parse_channel_username(page):
    try:
        msg = await page.wait_for_selector('div:has-text("Твое задание")', timeout=7000)
        content = await msg.inner_text()
        import re
        m = re.search(r"@([\w\d_]+)", content)
        if m:
            return m.group(1)
        return None
    except Exception as e:
        logging.error(f"Failed to parse channel username: {e}")
        return None

async def subscribe_to_channel(context, username):
    page = await context.new_page()
    try:
        channel_url = f"https://t.me/{username}"
        await page.goto(channel_url)
        await page.wait_for_timeout(3000)
        try:
            sub_btn = await page.wait_for_selector('button:has-text("Подписаться")', timeout=5000)
            await sub_btn.click()
            logging.info(f"Subscribed to channel @{username}")
        except Exception:
            logging.info(f"Already subscribed or subscribe button not found for @{username}")
        await page.wait_for_timeout(2000)
        await page.close()
    except Exception as e:
        logging.error(f"Error subscribing to channel @{username}: {e}")
        await page.close()

async def process_session(conn, referral, session):
    filename = session['filename']
    session_json = session['session_json']

    session_path = f"sessions/{filename}"
    with open(session_path, "w") as f:
        json.dump(session_json, f)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(storage_state=session_path)
            page = await context.new_page()

            logging.info(f"Session {filename} started for referral {referral['url']}")

            # Переходим по реферальной ссылке
            await page.goto(referral['url'])
            await page.wait_for_timeout(2000)

            # Вводим /start
            await page.fill('textarea', START_COMMAND)
            await page.keyboard.press('Enter')
            await page.wait_for_timeout(2000)

            # Жмем "Задания"
            await click_button_by_text(page, TASKS_BUTTON)

            for btn_text in BUTTONS:
                await click_button_by_text(page, btn_text)

                username = await parse_channel_username(page)
                if not username:
                    logging.error(f"Failed to parse username for button '{btn_text}'")
                    continue

                logging.info(f"Found channel username: {username}")

                await subscribe_to_channel(context, username)

                await page.bring_to_front()
                await page.wait_for_timeout(1000)

                await click_button_by_text(page, CHECK_BUTTON)
                await page.wait_for_timeout(1500)

                await click_button_by_text(page, BACK_BUTTON)
                await page.wait_for_timeout(1500)

            logging.info(f"Session {filename} done, marking as used.")
            await mark_session_used(conn, session['id'])

            await browser.close()

    except Exception as e:
        logging.error(f"Error processing session {filename}: {e}")

async def main():
    logging.info("Starting bot...")

    conn = await asyncpg.connect(DATABASE_URL)
    logging.info("Connected to DB")

    while True:
        referral, sessions = await get_referral_and_sessions(conn)

        if not referral or not sessions:
            logging.info("No referrals or sessions available, sleeping 5 minutes")
            await asyncio.sleep(RETRY_DELAY)
            continue

        logging.info(f"Working on referral: {referral['url']} with {len(sessions)} sessions")

        for session in sessions:
            await process_session(conn, referral, session)

if __name__ == "__main__":
    asyncio.run(main())
