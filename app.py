import os
import re
import time
import asyncio
import httpx
import socketio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, PlainTextResponse
from collections import defaultdict

# Configuration
SUBREDDIT = "AntiSemitismInReddit"
BATCH_SIZE = 100
API_URL = "https://api.pullpush.io/reddit/search/submission/"
REGEX_PATTERN = r'(?:^|\s|\[|/)/?r/([\w\d_]+)'

# State
# reports: { "worldnews": [{"title": "...", "url": "...", "id": "..."}, ...] }
reports = defaultdict(list)
processed_ids = set()
total_posts_processed = 0
is_running = False

# Socket.io Setup with increased timeouts for stability
sio = socketio.AsyncServer(
    async_mode='asgi', 
    cors_allowed_origins='*',
    ping_timeout=60,
    ping_interval=25
)
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
socket_app = socketio.ASGIApp(sio, app)

def extract_subreddits(title):
    """Extracts subreddit names from a post title using regex."""
    mentions = re.findall(REGEX_PATTERN, title, re.IGNORECASE)
    valid_mentions = list(set([m.lower() for m in mentions if m.lower() != SUBREDDIT.lower()]))
    return valid_mentions

async def scrape_task():
    global total_posts_processed, is_running
    is_running = True
    
    before = int(time.time())
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        while is_running:
            params = {
                "subreddit": SUBREDDIT,
                "limit": BATCH_SIZE,
                "before": before,
                "sort": "desc"
            }
            
            try:
                response = await client.get(API_URL, params=params)
                
                if response.status_code == 429:
                    print("Rate limited. Sleeping for 30s...")
                    await asyncio.sleep(30)
                    continue
                    
                if response.status_code != 200:
                    print(f"Error {response.status_code}: {response.text}")
                    await asyncio.sleep(10)
                    continue
                    
                data = response.json().get("data", [])
                if not data:
                    print("No more posts found.")
                    break
                
                for post in data:
                    post_id = post.get("id")
                    if post_id in processed_ids:
                        continue
                    
                    processed_ids.add(post_id)
                    title = post.get("title", "")
                    permalink = post.get("permalink", "")
                    full_url = f"https://www.reddit.com{permalink}"
                    
                    mentions = extract_subreddits(title)
                    
                    if mentions:
                        post_meta = {
                            "id": post_id,
                            "title": title,
                            "url": full_url
                        }
                        for sub in mentions:
                            reports[sub].append(post_meta)
                    
                    total_posts_processed += 1
                    before = post.get("created_utc")

                # Prepare summary: sorted list of [sub, count]
                summary = sorted(
                    [[sub, len(posts)] for sub, posts in reports.items()],
                    key=lambda x: x[1],
                    reverse=True
                )

                # Emit update with the FULL list
                await sio.emit("data_update", {
                    "top_subreddits": summary,
                    "total_processed": total_posts_processed,
                    "status": "Scanning..."
                })
                
                await asyncio.sleep(1.5)
                
            except httpx.RequestError as e:
                print(f"Network error: {e}")
                await asyncio.sleep(5)
            except Exception as e:
                print(f"Scrape error: {e}")
                await asyncio.sleep(5)

    summary = sorted([[sub, len(posts)] for sub, posts in reports.items()], key=lambda x: x[1], reverse=True)
    await sio.emit("data_update", {
        "top_subreddits": summary,
        "total_processed": total_posts_processed,
        "status": "Finished"
    })
    is_running = False

@app.get("/", response_class=HTMLResponse)
async def get_index():
    if os.path.exists("index.html"):
        with open("index.html", "r") as f:
            return f.read()
    return "index.html not found"

@app.get("/export", response_class=PlainTextResponse)
async def export_data():
    summary = sorted([[sub, len(posts)] for sub, posts in reports.items()], key=lambda x: x[1], reverse=True)
    lines = [f"r/{name} ({count})" for name, count in summary]
    return "\n".join(lines)

@sio.on("start_scan")
async def handle_start_scan(sid):
    global is_running
    if not is_running:
        asyncio.create_task(scrape_task())
        await sio.emit("status_change", {"message": "Scan started"}, to=sid)
    else:
        await sio.emit("status_change", {"message": "Scan already in progress"}, to=sid)

@sio.on("get_report")
async def handle_get_report(sid, sub_name):
    # Strip r/ if user sent it
    clean_name = sub_name.replace("r/", "").lower()
    post_list = reports.get(clean_name, [])
    await sio.emit("report_data", {
        "subreddit": clean_name,
        "posts": post_list
    }, to=sid)

@sio.on("reset_data")
async def handle_reset(sid):
    global reports, processed_ids, total_posts_processed, is_running
    reports = defaultdict(list)
    processed_ids = set()
    total_posts_processed = 0
    is_running = False
    await sio.emit("data_update", {
        "top_subreddits": [],
        "total_processed": 0,
        "status": "Ready"
    })

if __name__ == "__main__":
    import uvicorn
    # Render provides PORT environment variable
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(socket_app, host="0.0.0.0", port=port)
