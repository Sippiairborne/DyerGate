#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate || true

FILE=$(python -c "from app.backup import run_backup; print(run_backup() or '')")
if [ -z "$FILE" ]; then echo "Backup failed"; exit 1; fi

# Optional: upload to S3
if [ -n "${BACKUP_S3_BUCKET:-}" ]; then
  aws s3 cp "$FILE" "s3://${BACKUP_S3_BUCKET}/$(date +%Y/%m/%d)/$(basename "$FILE")"
  echo "Uploaded to s3://${BACKUP_S3_BUCKET}"
fi

# Retention: delete local backups older than 7 days
find ./data/backups -type f -mtime +7 -delete || true
echo "Backup OK: $FILE"
chmod +x scripts/backup.sh
# Add to crontab:
# 0 */6 * * * /opt/dyergate/scripts/backup.sh >> /var/log/dyergate-backup.log 2>&1
