#!/usr/bin/env bash
# DB를 pg_dump로 덤프해 gzip으로 저장하고 오래된 백업을 지운다. 운영 서버(VM2)에서 하루 한 번 돌린다.
# 서버를 새벽에 끄므로 04:00 cron 대신 anacron이 놓친 날을 보충하게 /etc/cron.daily/deltalog-backup에서 부른다(docs/SETUP.md 5-6).
# 날짜 폴더에 저장한다: <BACKUP_DIR>/2026-10-21/deltalog-1038.sql.gz
# 환경변수: BACKUP_DIR(저장 폴더, 기본 /root/backups/deltalog), BACKUP_KEEP_DAYS(보관 일수, 오늘 포함, 기본 30)
# 복원: gunzip -c <파일> | docker compose -f docker-compose.prod.yml exec -T db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"'
set -euo pipefail

dir="${BACKUP_DIR:-/root/backups/deltalog}"
keep="${BACKUP_KEEP_DAYS:-30}"
cd "$(dirname "$0")/.."
day="$dir/$(date +%F)"
mkdir -p "$day"

out="$day/deltalog-$(date +%H%M).sql.gz"
trap 'rm -f "$out.tmp"; rmdir "$day" 2>/dev/null || true' EXIT  # 중간에 실패해도 반쪽짜리 파일과 빈 날짜 폴더를 남기지 않는다
docker compose -f docker-compose.prod.yml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$out.tmp"

# 빈 덤프(연결 실패 등)가 정상 백업을 밀어내지 않게, 크기를 확인한 뒤에만 이름을 확정하고 오래된 것을 지운다
if [ "$(stat -c %s "$out.tmp")" -lt 10000 ]; then
  echo "$(date '+%F %T') 백업 실패: 덤프가 너무 작다" >&2
  exit 1
fi
mv "$out.tmp" "$out"
# 보관 기간이 지난 파일을 지우고, 비게 된 날짜 폴더도 지운다
find "$dir" -name 'deltalog-*.sql.gz' -mtime +"$((keep - 1))" -delete
find "$dir" -mindepth 1 -type d -empty -delete
echo "$(date '+%F %T') 백업 완료: $out ($(stat -c %s "$out") bytes)"