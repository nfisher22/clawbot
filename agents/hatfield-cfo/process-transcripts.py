import subprocess, json, os, re
from datetime import datetime

api_key = os.environ.get("FIREFLIES_API_KEY")
output_dir = os.path.expanduser("~/meeting-sync/transcripts")
os.makedirs(output_dir, exist_ok=True)

query = '{"query": "{ transcripts { id title date summary { overview } } }"}'

result = subprocess.run([
    "curl", "-s", "-X", "POST", "https://api.fireflies.ai/graphql",
    "-H", "Content-Type: application/json",
    "-H", f"Authorization: Bearer {api_key}",
    "-d", query
], capture_output=True, text=True)

data = json.loads(result.stdout)
transcripts = data["data"]["transcripts"]

for t in transcripts:
    title = re.sub(r'[^\w\s-]', '', t["title"]).strip().replace(" ", "_")
    date = datetime.fromtimestamp(t["date"]/1000).strftime("%Y-%m-%d")
    filename = f"{date}_{title}.txt"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w") as f:
        f.write(f"Title: {t['title']}\n")
        f.write(f"Date: {date}\n\n")
        if t.get("summary") and t["summary"].get("overview"):
            f.write(t["summary"]["overview"])
    print(f"Saved: {filename}")

print("Done.")
