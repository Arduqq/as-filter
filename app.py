import os
import re
import time
import asyncio
import httpx
import sqlite3
import json
from collections import defaultdict
from datetime import datetime, timezone

SUBREDDIT = "AntiSemitismInReddit"
BATCH_SIZE = 100
API_URL = "https://api.pullpush.io/reddit/search/submission/"
REGEX_PATTERN = r'(?<!\w)r/(\w+)'
DB_PATH = "data.db"
JSON_PATH = "data.json"
EXPORT_EVERY = 500  # posts between incremental JSON writes

# --- Database ---

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS posts
                 (id TEXT PRIMARY KEY, title TEXT, url TEXT, created_utc INTEGER,
                  upvotes INTEGER DEFAULT 0, archived INTEGER DEFAULT 0)''')
    try:
        c.execute("ALTER TABLE posts ADD COLUMN upvotes INTEGER DEFAULT 0")
    except: pass
    try:
        c.execute("ALTER TABLE posts ADD COLUMN archived INTEGER DEFAULT 0")
    except: pass
    c.execute('''CREATE TABLE IF NOT EXISTS mentions
                 (post_id TEXT, subreddit TEXT, FOREIGN KEY(post_id) REFERENCES posts(id))''')
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_mentions_unique ON mentions(post_id, subreddit)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_mentions_post_id ON mentions(post_id)')
    conn.commit()
    return conn

# --- State ---

processed_ids = set()
reports = defaultdict(list)
total_posts_processed = 0

def load_state():
    global total_posts_processed
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM posts")
    for (row_id,) in c.fetchall():
        processed_ids.add(row_id)
    c.execute('''SELECT m.subreddit, p.title, p.url, p.id, p.upvotes, p.archived, p.created_utc
                 FROM mentions m JOIN posts p ON m.post_id = p.id''')
    for sub, title, url, post_id, upvotes, archived, created_utc in c.fetchall():
        reports[sub].append({
            "title": title,
            "url": url,
            "id": post_id,
            "upvotes": upvotes or 0,
            "archived": bool(archived),
            "created_utc": created_utc,
        })
    c.execute("SELECT COUNT(*) FROM posts")
    total_posts_processed = c.fetchone()[0]
    conn.close()

# --- Core logic ---

def extract_subreddits(title):
    mentions = re.findall(REGEX_PATTERN, title, re.IGNORECASE)
    return list(set(m.lower() for m in mentions if m.lower() != SUBREDDIT.lower()))

def export_json():
    summary = sorted(reports.items(), key=lambda x: len(x[1]), reverse=True)

    def clean_posts(posts):
        return sorted(
            [p for p in posts if p.get("title", "").strip() != "[removed]"],
            key=lambda p: p.get("upvotes", 0),
            reverse=True,
        )

    cleaned = [(sub, clean_posts(posts)) for sub, posts in summary]
    cleaned = [(sub, posts) for sub, posts in cleaned if posts]

    all_posts_flat = [p for _, posts in cleaned for p in posts]
    valid_count = len(all_posts_flat)
    archived_count = sum(1 for p in all_posts_flat if p.get("archived"))
    dates = [p["created_utc"] for p in all_posts_flat if p.get("created_utc")]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_posts": valid_count,
        "raw_posts_collected": total_posts_processed,
        "removed_filtered": total_posts_processed - valid_count,
        "archived_posts": archived_count,
        "date_range": {
            "from": datetime.fromtimestamp(min(dates)).strftime("%Y-%m-%d") if dates else None,
            "to": datetime.fromtimestamp(max(dates)).strftime("%Y-%m-%d") if dates else None,
        },
        "total_subreddits": len(cleaned),
        "subreddits": [
            {
                "name": sub,
                "count": len(posts),
                "total_upvotes": sum(p.get("upvotes", 0) for p in posts),
                "last_report": max((p["created_utc"] for p in posts if p.get("created_utc")), default=None),
                "posts": posts,
            }
            for sub, posts in cleaned
        ],
    }
    with open(JSON_PATH, "w") as f:
        json.dump(payload, f)
    print(f"  → Exported {valid_count} posts / {len(cleaned)} subreddits ({archived_count} archived, {total_posts_processed - valid_count} removed) to {JSON_PATH}")

# --- Scraper ---

async def scrape():
    global total_posts_processed
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Always scan backward from now. For updates, stop when we reach posts
    # that predate the most recent entry in the DB (with a 1-day buffer).
    c.execute("SELECT MAX(created_utc) FROM posts")
    row = c.fetchone()
    stop_before = (row[0] - 86400) if row and row[0] else 0
    before = int(time.time())

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params = {"subreddit": SUBREDDIT, "limit": BATCH_SIZE, "before": before, "sort": "desc"}
            try:
                response = await client.get(API_URL, params=params)
                if response.status_code == 429:
                    print("Rate limited — sleeping 30s")
                    await asyncio.sleep(30)
                    continue
                if response.status_code != 200:
                    print(f"HTTP {response.status_code} — retrying")
                    await asyncio.sleep(10)
                    continue

                data = response.json().get("data", [])
                if not data:
                    print("No more posts — scraping complete.")
                    break

                batch_min_utc = min(post.get("created_utc", 0) for post in data)

                for post in data:
                    post_id = post.get("id")
                    if post_id in processed_ids:
                        continue
                    processed_ids.add(post_id)

                    # Skip posts removed by mods, Reddit, or the author
                    if post.get("removed_by_category") or post.get("title", "").strip() == "[removed]":
                        continue

                    title = post.get("title", "")
                    created_utc = post.get("created_utc")
                    upvotes = post.get("score", 0)
                    archived = 1 if post.get("archived", False) else 0
                    url = f"https://www.reddit.com{post.get('permalink', '')}"

                    c.execute(
                        "INSERT OR IGNORE INTO posts VALUES (?, ?, ?, ?, ?, ?)",
                        (post_id, title, url, created_utc, upvotes, archived),
                    )
                    for sub in extract_subreddits(title):
                        c.execute("INSERT OR IGNORE INTO mentions VALUES (?, ?)", (post_id, sub))
                        reports[sub].append({
                            "title": title,
                            "url": url,
                            "id": post_id,
                            "upvotes": upvotes,
                            "archived": bool(archived),
                            "created_utc": created_utc,
                        })
                    total_posts_processed += 1

                if batch_min_utc >= before:
                    print("No progress — reached the beginning of the archive.")
                    break
                before = batch_min_utc
                if stop_before and before < stop_before:
                    print("Caught up to existing data.")
                    break
                conn.commit()

                date_str = datetime.fromtimestamp(before).strftime("%Y-%m-%d")
                print(f"Posts: {total_posts_processed:,} | Scanning: {date_str}")

                if total_posts_processed % EXPORT_EVERY == 0:
                    export_json()

                await asyncio.sleep(2.0)

            except Exception as e:
                print(f"Error: {e}")
                await asyncio.sleep(5)

    conn.close()
    export_json()
    print("Done.")

if __name__ == "__main__":
    init_db()
    load_state()
    print(f"Loaded {total_posts_processed:,} posts from DB. Resuming scrape...")
    asyncio.run(scrape())
