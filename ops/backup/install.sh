#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) -eq 0 ]] || { echo 'Run on VPS as root' >&2; exit 1; }
base=$(cd -- "$(dirname -- "$0")" && pwd)
test -s /etc/media-knowledge/backup.json
test -s /etc/media-knowledge/backup-password
command -v restic >/dev/null
command -v rclone >/dev/null
install -d -m 755 /usr/local/libexec/media-knowledge
install -d -m 700 /var/lib/media-knowledge-backup
install -m 755 "$base/run.py" /usr/local/libexec/media-knowledge/backup.py
for unit in "$base"/systemd/*; do
  install -m 644 "$unit" "/etc/systemd/system/$(basename "$unit")"
done
systemd-analyze verify /etc/systemd/system/media-knowledge-backup.service /etc/systemd/system/media-knowledge-backup-verify.service
systemctl daemon-reload
echo 'Backup code and units installed. Run backup/verify/drill before enabling timers.'
