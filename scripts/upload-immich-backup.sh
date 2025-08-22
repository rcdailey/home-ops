#!/usr/bin/env bash

set -euo pipefail

# Script to upload Immich database backup to Garage S3
# Usage: ./upload-immich-backup.sh <path-to-backup-file>

BACKUP_FILE="${1:-}"
S3_BUCKET="immich-backups"
S3_ENDPOINT="http://192.168.1.58:3900"

if [[ -z "$BACKUP_FILE" ]]; then
    echo "Usage: $0 <path-to-immich_backup.sql>"
    echo "Example: $0 /path/to/immich_backup.sql"
    exit 1
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "Error: Backup file '$BACKUP_FILE' not found"
    exit 1
fi

echo "Uploading Immich backup to Garage S3..."
echo "File: $BACKUP_FILE"
echo "Endpoint: $S3_ENDPOINT"
echo "Bucket: $S3_BUCKET"

echo "Backup file to upload: $(ls -lh "$BACKUP_FILE")"

# Get S3 credentials from cluster-secrets
echo "Getting S3 credentials from cluster..."
S3_ACCESS_KEY=$(kubectl get secret cluster-secrets -o jsonpath='{.data.S3_ACCESS_KEY_ID}' | base64 -d)
S3_SECRET_KEY=$(kubectl get secret cluster-secrets -o jsonpath='{.data.S3_SECRET_ACCESS_KEY}' | base64 -d)
S3_REGION=$(kubectl get secret cluster-secrets -o jsonpath='{.data.S3_REGION}' | base64 -d)

export AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY"
export AWS_DEFAULT_REGION="$S3_REGION"
export AWS_ENDPOINT_URL="$S3_ENDPOINT"

# Create bucket if it doesn't exist
echo "Creating S3 bucket if it doesn't exist..."
aws s3 mb s3://$S3_BUCKET || echo "Bucket already exists or creation failed (continuing...)"

# Upload the backup
echo "Uploading backup..."
aws s3 cp "$BACKUP_FILE" s3://$S3_BUCKET/immich_backup.sql

# Verify upload
echo "Verifying upload..."
aws s3 ls s3://$S3_BUCKET/

echo "✅ Upload completed successfully!"
echo "The backup is now available at: s3://$S3_BUCKET/immich_backup.sql"
