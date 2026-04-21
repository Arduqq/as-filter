# Reddit Antisemitism Dashboard

> An audit of r/AntiSemitismInReddit to identify recurrent reports of antisemitism on various subreddits.

**[View the live dashboard →](https://illaveraqd.github.io/antisemitism-filter)**

---

## What this is

This dashboard is a moderation utility designed to empower users to remove themselves from spaces frequently reported as featuring antisemitic content. Posts from **r/AntiSemitismInReddit** are analyzed to identify subreddits that frequently host antisemitic content.

This tool is not intended to isolate you from ongoing debate, but to provide objective data for you to **moderate your own experience**. Use it to identify hotspots and manually mute subreddits that do not align with your safety standards.

## How to use the dashboard

**1. Browse the Data**
The full historical archive of r/AntiSemitismInReddit has been processed and is displayed on the dashboard.

**2. Verify Evidence**
Click any subreddit name to open a report showing the exact posts that triggered the mention. Read titles with care — not all spaces are inherently antisemitic.

**3. Take Action**
Use the Review button to visit a subreddit and decide if you wish to mute it.

---

## Data integrity

| Field | Detail |
|---|---|
| **Source** | PullPush API — archives Reddit submissions beyond the native 1k-post cap |
| **Coverage** | Full history from 2018 to present |
| **Filtering** | Posts removed by moderators or Reddit are excluded from the dataset |
| **Archived posts** | Posts Reddit has locked from new activity are shown with a grey border and dimmed text |
| **Algorithm** | Subreddit names are extracted from post titles using a regex negative-lookbehind pattern, catching mentions in parentheses, after commas, and in other non-spaced contexts that simpler patterns miss |
| **Transparency** | Every entry links to its original Reddit post. The full dataset is downloadable as JSON |

---

## Running the scraper locally

```bash
# Install the single dependency
pip install httpx

# Run — resumes automatically from data.db if it exists
python app.py
```

The scraper writes `data.json` every 500 posts and once more on completion. Open `index.html` via a local HTTP server to view the dashboard:

```bash
python -m http.server 8000
# then open http://localhost:8000
```

## Dataset files

| File | Description |
|---|---|
| `data.json` | Full dataset served to the dashboard |
| `data.db` | SQLite database used for incremental scraping |
| `app.py` | Scraper — run locally to update the dataset |
| `index.html` | Static dashboard — no build step required |

---

## Deployment

The dashboard is a static site — `index.html` + `data.json`. It can be hosted anywhere that serves static files.

### GitHub Pages (recommended, free)

1. Push this repository to GitHub
2. Go to **Settings → Pages**
3. Set source to **Deploy from a branch**, branch `main`, folder `/` (root)
4. GitHub will publish the site at `https://your-username.github.io/your-repo-name`
5. Update the link at the top of this README

### Keeping the data current

A GitHub Actions workflow (`.github/workflows/update-data.yml`) runs the scraper every Monday at 06:00 UTC, commits the updated `data.json` and `data.db`, and GitHub Pages redeploys automatically. No server required.

You can also trigger a manual update at any time from the **Actions** tab in your repository.
