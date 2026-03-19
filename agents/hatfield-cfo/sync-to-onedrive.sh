#!/bin/bash

# Meeting Sync Script
# Syncs Fireflies transcripts to OneDrive

ONEDRIVE_REMOTE="onedrive"
ONEDRIVE_DEST="Meetings"
LOG_FILE=~/meeting-sync/sync.log

echo "[$(date)] Starting meeting sync..." >> "$LOG_FILE"

rclone sync ~/meeting-sync/transcripts "$ONEDRIVE_REMOTE:$ONEDRIVE_DEST" \
  --log-file="$LOG_FILE" \
  --log-level INFO

echo "[$(date)] Sync complete." >> "$LOG_FILE"
