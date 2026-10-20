#!/usr/bin/env bash
# DB를 pg_dump로 덤프해 gzip으로 저장하고 오래된 백업을 지운다. 운영 서버(VM2)에서 cron으로 하루 한 번 돌린다.
#   0 4 * * * /root/workspace/deltalog/scripts/backup_db.sh >> /root/backups/deltalog/backup.log 2>&1
# 환경변수: BACKUP_DIR(저장 폴더, 기본 /root/backups/deltalog), BACKUP_KEEP_DAYS(보관 일수, 기본 14)
# 복원: gunzip -c <파일> | docker compose -f docker-compose.prod.yml exec -T db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"'
set -euo pipefail

dir="${BACKUP_DIR:-/root/backups/deltalog}"
keep="${BACKUP_KEEP_DAYS:-14}"
cd "$(dirname "$0")/.."
mkdir -p "$dir"

out="$dir/deltalog-$(date +%Y%m%d-%H%M).sql.gz"
trap 'rm -f "$out.tmp"' EXIT  # 중간에 실패해도 반쪽짜리 파일을 남기지 않는다
docker compose -f docker-compose.prod.yml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$out.tmp"

# 빈 덤프(연결 실패 등)가 정상 백업을 밀어내지 않게, 크기를 확인한 뒤에만 이름을 확정하고 오래된 것을 지운다
if [ "$(stat -c %s "$out.tmp")" -lt 10000 ]; then
  echo "$(date '+%F %T') 백업 실패: 덤프가 너무 작다" >&2
  exit 1
fi
mv "$out.tmp" "$out"
find "$dir" -name 'deltalog-*.sql.gz' -mtime +"$keep" -delete
echo "$(date '+%F %T') 백업 완료: $out ($(stat -c %s "$out") bytes)"