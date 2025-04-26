# Telegraph / Telegram Image Scraper 📸

Asynchronously download every image referenced in [Telegraph](https://telegra.ph) / [Graph](https://graph.org) pages and in Telegram posts and channels you can access – with built‑in deduplication, resumable state and polite rate‑limits.

> **Heads‑up ⚠️**  This project is meant for *personal* archiving/backup.  Scraping other people’s content may violate the Telegram & Telegraph Terms of Service and/or local copyright law.  **Use responsibly.**

---

## ✨ Features

|                                   |                                                                                                                 |
|-----------------------------------|-----------------------------------------------------------------------------------------------------------------|
| **One‑liner setup**               | `python telegraph_scraper.py` – the first run interactively asks for API ID/HASH & save folder; no flags needed |
| **Multiple link types**           | • Telegraph \( `https://telegra.ph/slug` )  • Graph  • Telegram `t.me/c/…/…` individual posts  • whole channels |
| **Async & rate‑limited**          | Global semaphores keep calls well below Telegram’s fair‑use window                                              |
| **Never re‑downloads**            | Tiny SQLite DB `processed_links.db` remembers every URL + timestamp                                             |
| **Resilient**                     | Gracefully skips 4xx/5xx HTTP errors, RPC errors **and** private channels you’re not part of                   |
| **Totally offline cache**         | Saves raw `page.html` beside every image so you can inspect later                                               |

---

## 🛠️  Requirements

* Python ≥ 3.9  (tested on 3.9 → 3.12)
* A Telegram API ID & HASH  — <https://my.telegram.org/apps>
* `pip install -r requirements.txt`

### `requirements.txt`
```
telethon>=1.35.0
httpx>=0.27.0
beautifulsoup4>=4.12
lxml>=5.2         # optional but faster HTML parsing
```

---

## 🚀 Installation

```bash
# clone the repo
$ git clone https://github.com/<your‑handle>/telegraph-scraper.git
$ cd telegraph-scraper

# create & activate a virtual‑env (recommended)
$ python -m venv .venv && source .venv/bin/activate

# install deps
$ pip install -r requirements.txt
```

---

## ▶️ Usage

```bash
$ python telegraph_scraper.py
```

You will be prompted for:

| Prompt                                           | Example input                                  |
|--------------------------------------------------|-----------------------------------------------|
| **Save directory**                               | `telegraph_images` (press Enter for default)   |
| **Download entire channel?** `(y/n)`             | `y` to walk the whole message history          |
| **Telegram login**                               | Enter your phone number & the code Telegram sends |
| **Target list**                                  | `@big_channel, https://telegra.ph/abc-123, all` |

After that the scraper prints progress:

```
↳ Telegraph page: https://telegra.ph/abc-123
↳ 12 images detected on … downloading…
↳ Telegram post: https://t.me/c/123456789/42
    ▸ IMG_20250426_090000.jpg
```

### What does **all** do?

Typing `all` crawls *every* dialog you can see in your Telegram client.  The script automatically skips private channels you don’t belong to, so it won’t crash when it encounters a `t.me/c/...` link it can’t resolve.

---

## ⚙️ Configuration

Variable | Purpose | Default
---------|---------|---------
`IMG_CONCURRENCY` | Max simultaneous image downloads per page | **10**
`LINK_CONCURRENCY` | Max pages/posts scraped in parallel | **4**

Edit the constants at the top of `telegraph_scraper.py` if you need to back off further (e.g. a very slow VPS).

---

## 🗄️ Data & Cache layout

```
telegraph_images/
├── abc-123/               # Telegraph slug
│   ├── page.html
│   ├── 1.jpg 2.jpg …
├── tg_123456789_42/       # Telegram post cache
│   └── IMG_0001.png …
processed_links.db          # tiny sqlite (primary‑key is URL)
```

Delete `processed_links.db` to force a fresh download next run.

---

## 🐛 Troubleshooting

| Symptom | Fix |
|---------|-----|
| **`ValueError: Could not find the input entity for PeerChannel`** | You tried to crawl a private channel you’re not in.  The current version logs a warning and continues. |
| **HTTP 429 / 420** | Lower `IMG_CONCURRENCY` and `LINK_CONCURRENCY`; wait a bit. |
| **`ModuleNotFoundError: lxml`** | Either `pip install lxml` or remove it from `requirements.txt`. |

---

## 🙋 FAQ

**Q. Why interactive `input()` prompts instead of CLI flags?**  
A. Simpler for casual users; the core functions accept parameters so you can wrap them in `argparse` if you prefer.

**Q. Can I run this non‑interactively?**  
Yes – create a `credentials.json` with your API ID/HASH|SESSION_NAME ahead of time, and pipe the inputs:
```bash
echo "telegraph_images\ny\n@mychannel" | python telegraph_scraper.py
```

---
