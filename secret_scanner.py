#!/usr/bin/env python3
"""
Hatfield Secret Scanner — scans clawbot scripts for exposed credentials
Runs natively, no external dependencies required
"""
import re
import os
from pathlib import Path
from datetime import datetime

SCAN_DIRS = ["/opt/clawbot/app", "/opt/clawbot/data", "/root"]
SKIP_DIRS = ["/opt/clawbot/app/venv", "/root/node_modules"]
SCAN_EXTENSIONS = [".py", ".sh", ".md", ".env", ".json", ".yaml", ".yml"]
SKIP_FILES = ["secret_scanner.py"]
SKIP_PATHS = ["/root/.env"]

PATTERNS = {
    "OpenAI API Key":       r"sk-[a-zA-Z0-9]{20,}",
    "Telegram Bot Token":   r"\d{8,10}:AA[a-zA-Z0-9_-]{33}",
    "Vault Token":          r"hvs\.[a-zA-Z0-9]{20,}",
    "Tavily API Key":       r"tvly-[a-zA-Z0-9_-]{20,}",
    "Generic API Key":      r"(?i)(api[_-]?key|apikey|secret|token)\s*[=:]\s*['\"]?[a-zA-Z0-9_\-]{20,}['\"]?",
    "Private Key Block":    r"-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----",
}

findings = []

for scan_dir in SCAN_DIRS:
    for path in Path(scan_dir).rglob("*"):
        if not path.is_file():
            continue
        if any(str(path).startswith(skip) for skip in SKIP_DIRS):
            continue
        if path.suffix not in SCAN_EXTENSIONS and path.name not in [".env"]:
            continue
        if path.name in SKIP_FILES or str(path) in SKIP_PATHS:
            continue
        try:
            content = path.read_text(errors="ignore")
            for pattern_name, pattern in PATTERNS.items():
                matches = re.findall(pattern, content)
                if matches:
                    findings.append({
                        "file": str(path),
                        "pattern": pattern_name,
                        "count": len(matches)
                    })
        except Exception:
            continue

timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
log_path = Path("/opt/clawbot/logs/secret_scan.log")
log_path.parent.mkdir(parents=True, exist_ok=True)

with open(log_path, "a") as f:
    f.write(f"\n=== Secret Scan {timestamp} ===\n")
    if findings:
        for finding in findings:
            line = f"  ⚠️  {finding['file']} — {finding['pattern']} ({finding['count']} match)\n"
            f.write(line)
            print(line, end="")
    else:
        f.write("  ✅ No secrets found in scanned files\n")
        print("  ✅ No secrets found in scanned files")

print(f"\nLog saved to {log_path}")
