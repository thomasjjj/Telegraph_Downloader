
#!/usr/bin/env python3
"""
telegraph_scraper.py

Async utility for downloading images from Telegraph / Graph pages
and Telegram posts or entire channels.

◂ 2025-04-26 – GitHub-ready edition ▸
  * PEP-8 / Ruff-clean formatting
  * Clarified docstrings & comments
  * Safety: no secrets printed; credential & DB files are git-ignored
  * Same interactive *input()* workflow the original author prefers
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import httpx
from bs4 import BeautifulSoup
from telethon import TelegramClient
from telethon.errors import RPCError
from telethon.tl.types import InputMessagesFilterUrl

# ─────────────────────────── CONSTANTS ──────────────────────────── #

CREDENTIALS_FILE: Final = "credentials.json"
DB_PATH: Final = "processed_links.db"

IMG_CONCURRENCY: Final = 10  # max concurrent image downloads per page
LINK_CONCURRENCY: Final = 4  # max concurrent page/post scrapes

TGRAPH_PATTERN: Final = r"https?://telegra\.ph/[\w-]+"
GRAPH_PATTERN: Final = r"https?://graph\.org/[\w-]+"
TG_MSG_PATTERN: Final = r"https?://t\.me/c/\d+/\d+"

TELEGRAPH_REGEX = re.compile(TGRAPH_PATTERN)
GRAPH_REGEX = re.compile(GRAPH_PATTERN)
TELEGRAM_MSG_REGEX = re.compile(TG_MSG_PATTERN)

# ───────────────────────────── LOGGER ───────────────────────────── #

log = logging.getLogger("tg_scraper")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)

# ──────────────────────────── DB SETUP ──────────────────────────── #


def ensure_db() -> None:
    """Create or migrate the processed_links table."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS processed_links(link TEXT PRIMARY KEY)"
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(processed_links)")}
        if "kind" not in cols:
            conn.execute("ALTER TABLE processed_links ADD COLUMN kind TEXT")
        if "downloaded_at" not in cols:
            conn.execute(
                "ALTER TABLE processed_links ADD COLUMN downloaded_at DATETIME"
            )


def link_processed(link: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        return (
            conn.execute(
                "SELECT 1 FROM processed_links WHERE link = ? LIMIT 1", (link,)
            ).fetchone()
            is not None
        )


def mark_done(link: str, kind: str) -> None:
    """Record a processed link with timestamp."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO processed_links(link, kind, downloaded_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP)",
                (link, kind),
            )
    except sqlite3.IntegrityError:
        pass  # already recorded


# ────────────────────── GLOBAL SEMAPHORES ───────────────────────── #

PAGE_SEM = asyncio.Semaphore(LINK_CONCURRENCY)
IMG_SEM = asyncio.Semaphore(IMG_CONCURRENCY)

# ────────────────────────── HTTP HELPERS ────────────────────────── #


async def _download_img(client: httpx.AsyncClient, url: str, folder: Path) -> None:
    async with IMG_SEM:
        try:
            fname = folder / Path(url).name
            if fname.exists():
                return
            resp = await client.get(url, follow_redirects=True, timeout=30)
            resp.raise_for_status()
            fname.write_bytes(resp.content)
            print(f"    ▸ {fname.name}")
        except Exception as exc:  # noqa: BLE001
            log.warning("Image download failed %s – %s", url, exc)


async def _scrape_page(url: str, base: str, out: Path, kind: str) -> None:
    if link_processed(url):
        return

    out.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (tg_scraper)"}
    ) as client:
        try:
            resp = await client.get(url, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            log.warning("Page fetch failed %s (status %s)", url, e.response.status_code)
            return
        except Exception as e:  # noqa: BLE001
            log.warning("Error fetching %s – %s", url, e)
            return

        (out / "page.html").write_text(resp.text, encoding="utf-8")
        soup = BeautifulSoup(resp.text, "html.parser")
        img_urls = {
            src if not src.startswith("/") else f"{base}{src}"
            for src in (img.get("src") or "" for img in soup.find_all("img"))
            if src
        }

        if not img_urls:
            log.info("No images on %s", url)
            mark_done(url, kind)
            return

        print(f"↳ {len(img_urls)} images detected on {url}, downloading…")
        await asyncio.gather(*[_download_img(client, u, out) for u in img_urls])
        mark_done(url, kind)


# ──────────────────────────── HANDLERS ──────────────────────────── #


async def handle_telegraph(link: str, root: Path) -> None:
    async with PAGE_SEM:
        print(f"↳ Telegraph page: {link}")
        await _scrape_page(
            link, "https://telegra.ph", root / Path(link).name, "telegraph"
        )


async def handle_graph(link: str, root: Path) -> None:
    async with PAGE_SEM:
        print(f"↳ Graph page: {link}")
        await _scrape_page(link, "https://graph.org", root / Path(link).name, "graph")




async def handle_tg_post(client: TelegramClient, link: str, root: Path) -> None:
    async with PAGE_SEM:
        if link_processed(link):
            return
        chan_part, msg_id = link.rstrip("/").split("/")[-2:]
        chan_id = int(f"-100{chan_part}")
        try:
            entity = await client.get_entity(chan_id)        # ← may fail
            msg = await client.get_messages(entity, ids=int(msg_id))
            if not (msg and msg.media):
                log.info("No media in %s", link)
                return
            folder = root / f"tg_{chan_part}_{msg_id}"
            folder.mkdir(parents=True, exist_ok=True)
            print(f"↳ Telegram post: {link}")
            await msg.download_media(file=str(folder))
            mark_done(link, "telegram")

        # NEW: skip channels we can’t access
        except (RPCError, ValueError) as exc:
            log.warning("Cannot access %s – %s", link, exc)



async def crawl_channel(
    client: TelegramClient, entity, root: Path, full: bool
) -> None:  # type: ignore[valid-type]
    print(f"═══ Crawling {entity.title} ═══")
    async for msg in client.iter_messages(entity, filter=InputMessagesFilterUrl):
        if not msg.text:
            continue
        tasks: list[asyncio.Task] = []
        tasks.extend(handle_telegraph(u, root) for u in TELEGRAPH_REGEX.findall(msg.text))
        tasks.extend(handle_graph(u, root) for u in GRAPH_REGEX.findall(msg.text))
        tasks.extend(
            handle_tg_post(client, u, root) for u in TELEGRAM_MSG_REGEX.findall(msg.text)
        )
        if tasks:
            await asyncio.gather(*tasks)
        if not full:
            break


# ───────────────────────── CREDENTIALS ────────────────────────── #


@dataclass
class Credentials:
    api_id: int
    api_hash: str
    session_name: str

    @classmethod
    def load(cls) -> "Credentials":
        """
        Load credentials from *credentials.json*, or create it interactively
        the first time the script is run.
        """
        path = Path(CREDENTIALS_FILE)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            print("Credentials not found—creating new file")
            data: dict[str, str] = {
                "API_ID": input("API_ID: ").strip(),
                "API_HASH": input("API_HASH: ").strip(),
                "SESSION_NAME": (
                    input("Session name (default tg_scraper): ").strip() or "tg_scraper"
                ),
            }
            path.write_text(json.dumps(data, indent=4), encoding="utf-8")
        return cls(int(data["API_ID"]), data["API_HASH"], data["SESSION_NAME"])


# ────────────────────────────── MAIN ───────────────────────────── #


async def main() -> None:
    """Entry-point coroutine – runs the interactive workflow."""
    ensure_db()
    save_root = Path(
        input("Save directory (default 'telegraph_images'): ").strip()
        or "telegraph_images"
    )
    save_root.mkdir(parents=True, exist_ok=True)
    full_crawl = (
        input("Download entire channel? (y/n): ").strip().lower() in {"y", "yes"}
    )

    creds = Credentials.load()
    client = TelegramClient(creds.session_name, creds.api_id, creds.api_hash)
    await client.start()

    try:
        print("\nEnter @usernames, t.me/c links, or 'all':")
        entries = [e.strip() for e in sys.stdin.readline().split(",") if e.strip()]

        if len(entries) == 1 and entries[0].lower() == "all":
            async for dlg in client.iter_dialogs():
                if dlg.is_channel or dlg.is_group:
                    await crawl_channel(client, dlg.entity, save_root, full_crawl)
            return

        seen: set[int] = set()
        for entry in entries:
            # @username or bare channel
            if entry.startswith("@") or (entry and not entry.startswith("http")):
                try:
                    ent = await client.get_entity(entry)
                    if ent.id in seen:
                        continue
                    seen.add(ent.id)
                    await crawl_channel(client, ent, save_root, full_crawl)
                except RPCError as exc:
                    log.error("Channel error %s – %s", entry, exc)
                continue

            # t.me/c/... message link
            if TELEGRAM_MSG_REGEX.fullmatch(entry):
                if full_crawl:
                    chan_part = entry.rstrip("/").split("/")[-2]
                    chan_id = int(f"-100{chan_part}")
                    if chan_id in seen:
                        continue
                    seen.add(chan_id)
                    try:
                        ent = await client.get_entity(chan_id)
                        await crawl_channel(client, ent, save_root, full_crawl)
                    except RPCError as exc:
                        log.error("Cannot crawl %s – %s", entry, exc)
                else:
                    await handle_tg_post(client, entry, save_root)
                continue

            # direct Telegraph / Graph
            if TELEGRAPH_REGEX.fullmatch(entry):
                await handle_telegraph(entry, save_root)
                continue
            if GRAPH_REGEX.fullmatch(entry):
                await handle_graph(entry, save_root)
                continue

            log.warning("Unrecognised input: %s", entry)

    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted – goodbye!")
