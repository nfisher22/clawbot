#!/usr/bin/env python3
"""
Hatfield Script Audit — tracks every script run with timing and outcome
Import and use run_audited() to wrap any script's main function
"""
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

AUDIT_LOG = "/opt/clawbot/logs/audit.log"
SCRIPT_LOG = "/opt/clawbot/logs/scripts_audit.log"

def _write(path, line):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(line + "\n")

def run_audited(script_name: str, fn, *args, **kwargs):
    """Run a function and log the result to both audit logs."""
    ts_start = datetime.now(timezone.utc)
    start_str = ts_start.strftime("%Y-%m-%d %H:%M:%S UTC")
    t0 = time.time()
    try:
        result = fn(*args, **kwargs)
        duration = round(time.time() - t0, 2)
        line = f"{start_str} | SUCCESS | {script_name} | completed in {duration}s"
        _write(AUDIT_LOG, line)
        _write(SCRIPT_LOG, line)
        print(line)
        return result
    except Exception as e:
        duration = round(time.time() - t0, 2)
        tb = traceback.format_exc().strip().split("\n")[-1]
        line = f"{start_str} | ERROR | {script_name} | failed in {duration}s — {tb}"
        _write(AUDIT_LOG, line)
        _write(SCRIPT_LOG, line)
        print(line)
        raise

def log_script_start(script_name: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"{ts} | START | {script_name} | initiated"
    _write(AUDIT_LOG, line)
    _write(SCRIPT_LOG, line)

def log_script_end(script_name: str, duration: float, status: str = "SUCCESS", detail: str = ""):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"{ts} | {status} | {script_name} | {detail} ({duration}s)"
    _write(AUDIT_LOG, line)
    _write(SCRIPT_LOG, line)
