#!/usr/bin/env python3
"""
Hatfield Task Queue — priority task management with checkpointing
Statuses: pending, in_progress, blocked, completed
Priorities: high, normal, low
"""
import json
import os
from datetime import datetime, timezone

TASK_FILE = "/opt/clawbot/logs/task_queue.json"
AUDIT_LOG = "/opt/clawbot/logs/audit.log"

def audit(level, script, message):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"{ts} | {level} | {script} | {message}\n"
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(line)
    except Exception:
        pass

def load_tasks():
    try:
        with open(TASK_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"tasks": [], "completed": [], "last_updated": ""}

def save_tasks(data):
    data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        with open(TASK_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        audit("ERROR", "task-queue", f"Failed to save tasks: {e}")

def add_task(title, description="", source="telegram", priority="normal", due_date=None):
    data = load_tasks()
    task_id = len(data["tasks"]) + len(data["completed"]) + 1
    task = {
        "id": task_id,
        "title": title,
        "description": description or title,
        "source": source,
        "priority": priority,
        "status": "pending",
        "due_date": due_date or "",
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    }
    data["tasks"].append(task)
    save_tasks(data)
    audit("INFO", "task-queue", f"Task added [{priority}]: {title}")
    return task_id

def update_task_status(task_id, status):
    """Update status: pending, in_progress, blocked, completed"""
    data = load_tasks()
    for task in data["tasks"]:
        if task["id"] == task_id:
            task["status"] = status
            task["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            if status == "completed":
                task["completed_at"] = task["updated"]
                data["completed"].append(task)
                data["tasks"].remove(task)
                audit("SUCCESS", "task-queue", f"Task completed: {task['title']}")
            else:
                audit("INFO", "task-queue", f"Task #{task_id} → {status}")
            save_tasks(data)
            return True
    return False

def complete_task(task_id):
    return update_task_status(task_id, "completed")

def get_pending_tasks(priority=None):
    data = load_tasks()
    tasks = data["tasks"]
    if priority:
        tasks = [t for t in tasks if t.get("priority") == priority]
    # Sort by priority: high → normal → low
    priority_order = {"high": 0, "normal": 1, "low": 2}
    return sorted(tasks, key=lambda t: priority_order.get(t.get("priority", "normal"), 1))

def get_task_summary():
    data = load_tasks()
    tasks = data["tasks"]
    high = [t for t in tasks if t.get("priority") == "high"]
    normal = [t for t in tasks if t.get("priority") == "normal"]
    low = [t for t in tasks if t.get("priority") == "low"]
    lines = [f"📋 *Task Queue* — {len(tasks)} pending, {len(data['completed'])} completed"]
    if high:
        lines.append("\n🔴 *High Priority*")
        for t in high:
            lines.append(f"  #{t['id']} — {t['title']} [{t['status']}]")
    if normal:
        lines.append("\n🟡 *Normal Priority*")
        for t in normal:
            lines.append(f"  #{t['id']} — {t['title']} [{t['status']}]")
    if low:
        lines.append("\n⚪ *Low Priority*")
        for t in low:
            lines.append(f"  #{t['id']} — {t['title']} [{t['status']}]")
    return "\n".join(lines)

if __name__ == "__main__":
    print("Testing task queue...")
    tid = add_task("Test upgraded queue", "Testing priority queue", priority="high")
    print(f"Added task #{tid}")
    print(get_task_summary())
    complete_task(tid)
    print(f"Task #{tid} completed")
