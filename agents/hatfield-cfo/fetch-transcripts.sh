#!/bin/bash

# Fireflies Transcript Fetch Script
API_KEY="$FIREFLIES_API_KEY"
OUTPUT_DIR=~/meeting-sync/transcripts
LOG_FILE=~/meeting-sync/sync.log

echo "[$(date)] Fetching transcripts from Fireflies..." >> "$LOG_FILE"

curl -s -X POST https://api.fireflies.ai/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"query": "{ transcripts { id title date summary { overview } } }"}' \
  -o "$OUTPUT_DIR/transcripts_raw.json"

echo "[$(date)] Fetch complete." >> "$LOG_FILE"
