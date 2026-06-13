#!/bin/bash
# Oracle vault(정본!) 일일 백업 — chocolat의 LaunchAgent h59.oracle.vault-backup이 호출.
# 매일 03:20. corpus(사진·평문 정본) + digest + journal + index 를
# ~/data/backups/oracle-vault/YYYY-MM-DD/ 스냅샷으로.
#
# rsync --link-dest 하드링크 증분 — 변경 없는 파일(사진 대부분)은 디스크를 거의 안 먹음.
# 14일 이상 된 스냅샷은 삭제. Mongo는 별도 주간 백업(backup-mongo.sh) — vault가 정본이라
# 이 백업이 사실상 데이터 보호의 핵심.

set -euo pipefail

SRC_ROOT="$HOME/projects/oracle"
BACKUP_DIR="$HOME/data/backups/oracle-vault"
mkdir -p "$BACKUP_DIR"

TODAY=$(date +%Y-%m-%d)
DEST="$BACKUP_DIR/$TODAY"
LATEST="$BACKUP_DIR/latest"

echo "[$(date)] Oracle vault 백업 시작 → $DEST"
mkdir -p "$DEST"
for d in corpus digest journal index; do
    [ -d "$SRC_ROOT/$d" ] || continue
    if [ -d "$LATEST/$d" ]; then
        # 이전 스냅샷과 동일한 파일은 하드링크 (macOS bash 3.2 호환 — 배열 확장 회피)
        rsync -a --delete --link-dest="$LATEST/$d" "$SRC_ROOT/$d/" "$DEST/$d/"
    else
        rsync -a --delete "$SRC_ROOT/$d/" "$DEST/$d/"
    fi
done

# latest 심볼릭 링크 갱신 (다음 증분의 기준)
ln -sfn "$DEST" "$LATEST"

# 14일 이상 된 스냅샷 정리 (latest 링크 제외)
find "$BACKUP_DIR" -maxdepth 1 -type d -name "20*" -mtime +14 -exec rm -rf {} +

echo "[$(date)] 완료. 스냅샷 목록:"
ls -d "$BACKUP_DIR"/20* 2>/dev/null | tail -5
du -sh "$BACKUP_DIR" 2>/dev/null | tail -1
