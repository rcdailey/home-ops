#!/bin/sh
set -e

count=$(python -m paperless classify inbox 2>&1 | head -1)
case "$count" in
  "inbox empty")
    echo "No documents to classify, skipping."
    exit 0
    ;;
esac

exec opencode run \
  --agent paperless-classifier \
  --dangerously-skip-permissions \
  "Classify all documents in the paperless inbox."
