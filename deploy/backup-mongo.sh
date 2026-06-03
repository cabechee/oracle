#!/bin/bash
# Oracle MongoDB 주간 백업 — chocolat의 LaunchAgent h59.oracle.mongo-backup이 호출.
# 매주 일요일 03:00. ~/data/backups/oracle-mongo/ 에 archive 누적, 4주 이상 된 건 삭제.

set -euo pipefail

BACKUP_DIR="$HOME/data/backups/oracle-mongo"
mkdir -p "$BACKUP_DIR"

TODAY=$(date +%Y-%m-%d)
OUT="$BACKUP_DIR/oracle-$TODAY.archive"

# mongodump 경로 (Apple Silicon brew)
MONGODUMP="/opt/homebrew/bin/mongodump"
if [ ! -x "$MONGODUMP" ]; then
    MONGODUMP="mongodump"
fi

echo "[$(date)] Oracle Mongo 백업 시작 → $OUT"
"$MONGODUMP" --db oracle --archive="$OUT" --gzip

# 4주(28일) 이상 된 백업 정리
find "$BACKUP_DIR" -name "oracle-*.archive" -mtime +28 -delete

echo "[$(date)] 완료. 현재 백업 목록:"
ls -lh "$BACKUP_DIR" | tail -10
