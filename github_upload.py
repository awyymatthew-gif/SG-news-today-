"""
Upload all bot files to GitHub repo via the GitHub API.
Usage: python3 github_upload.py <GITHUB_TOKEN>
"""
import sys
import os
import base64
import requests

TOKEN = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GITHUB_TOKEN", "")
REPO = "awyymatthew-gif/SG-news-today-"
BRANCH = "main"
API_BASE = f"https://api.github.com/repos/{REPO}/contents"

HEADERS = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

# Files to upload (relative to this script's directory)
FILES = [
    "bot.py",
    "listener.py",
    "sources.py",
    "scorer.py",
    "digest.py",
    "config.py",
    "render.yaml",
    "requirements.txt",
    "README.md",
    "start_listener.sh",
    ".gitignore",
]

BOT_DIR = os.path.dirname(os.path.abspath(__file__))

def upload_file(filepath, filename):
    with open(filepath, "rb") as f:
        content = base64.b64encode(f.read()).decode("utf-8")

    url = f"{API_BASE}/{filename}"
    
    # Check if file already exists (to get SHA for update)
    resp = requests.get(url, headers=HEADERS)
    sha = resp.json().get("sha") if resp.status_code == 200 else None

    payload = {
        "message": f"Add {filename}",
        "content": content,
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha
        payload["message"] = f"Update {filename}"

    resp = requests.put(url, json=payload, headers=HEADERS)
    if resp.status_code in (200, 201):
        print(f"✅ {filename}")
    else:
        print(f"❌ {filename}: {resp.status_code} {resp.json().get('message', '')}")

if not TOKEN:
    print("ERROR: No GitHub token provided.")
    sys.exit(1)

print(f"Uploading {len(FILES)} files to {REPO}...")
for fname in FILES:
    fpath = os.path.join(BOT_DIR, fname)
    if os.path.exists(fpath):
        upload_file(fpath, fname)
    else:
        print(f"⚠️  Skipped (not found): {fname}")

print("\nDone! Check: https://github.com/" + REPO)
