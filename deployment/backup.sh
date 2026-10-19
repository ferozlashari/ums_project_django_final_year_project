#!/usr/bin/env bash
# Database + media backup with retention.  Run from cron, e.g. daily at 02:30:
#   30 2 * * * cd /srv/ums && set -a && . /etc/ums/ums.env && set +a && bash deployment/backup.sh
# Needs: pg_dump (PostgreSQL) or sqlite3, tar. Writes to $BACKUP_DIR (default ./backups).
#
# NOT included on purpose: FIELD_ENCRYPTION_KEY and DJANGO_SECRET_KEY. Without the encryption
# key a restored database cannot decrypt CNIC fields - store that key separately and safely
# (password manager / secrets vault), never in the same place as the backups.
set -euo pipefail
BACKUP_DIR="${BACKUP_DIR:-./backups}"; KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"; mkdir -p "$BACKUP_DIR"

if [ -n "${DATABASE_URL:-}" ] || [ "${DB_ENGINE:-sqlite}" = "postgresql" ]; then
  if [ -n "${DATABASE_URL:-}" ]; then pg_dump --no-owner --format=custom "$DATABASE_URL" > "$BACKUP_DIR/db-$STAMP.dump"
  else PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_dump --no-owner --format=custom -h "${POSTGRES_HOST:-localhost}" \
         -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-umsuser}" "${POSTGRES_DB:-ums}" > "$BACKUP_DIR/db-$STAMP.dump"; fi
else
  sqlite3 "${SQLITE_NAME:-db.sqlite3}" ".backup '$BACKUP_DIR/db-$STAMP.sqlite3'"
fi
[ -d media ] && tar -czf "$BACKUP_DIR/media-$STAMP.tar.gz" media
find "$BACKUP_DIR" -type f \( -name 'db-*' -o -name 'media-*' \) -mtime +"$KEEP_DAYS" -delete
echo "Backup written to $BACKUP_DIR (kept $KEEP_DAYS days)"
# Restore (PostgreSQL):  pg_restore --clean --no-owner -d "$DATABASE_URL" backups/db-<stamp>.dump
#                         tar -xzf backups/media-<stamp>.tar.gz
# Then run:  python manage.py migrate && python manage.py production_check
# Test a restore on a scratch database regularly - an untested backup is not a backup.
