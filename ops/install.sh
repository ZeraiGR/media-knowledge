#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) -eq 0 ]] || { echo 'Run as root on the VPS' >&2; exit 1; }
base=$(cd -- "$(dirname -- "$0")" && pwd)
install -d -m 700 /opt/media-knowledge
install -m 600 "$base/compose.yaml" /opt/media-knowledge/compose.yaml
install -d -m 755 /usr/local/libexec/media-knowledge
install -m 755 "$base/deploy.py" /usr/local/libexec/media-knowledge/deploy
if [[ ! -f /opt/media-knowledge/secrets.env ]]; then
  (umask 077; printf 'POSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 32)" > /opt/media-knowledge/secrets.env)
fi
if [[ ! -f /opt/media-knowledge/images.env ]]; then
  (umask 077; printf '%s\n' 'SERVER_IMAGE=ghcr.io/zeraigr/media-knowledge-server:bootstrap' 'WEB_IMAGE=ghcr.io/zeraigr/media-knowledge-web:bootstrap' > /opt/media-knowledge/images.env)
fi
if ! id media-deploy >/dev/null 2>&1; then
  useradd --create-home --shell /bin/sh media-deploy
fi
install -d -m 700 -o media-deploy -g media-deploy /home/media-deploy/.ssh
[[ -f "$base/server.pub" && -f "$base/web.pub" ]] || { echo 'Supply two dedicated deployment public keys' >&2; exit 1; }
{
  printf 'restrict,command="/usr/bin/sudo -n /usr/local/libexec/media-knowledge/deploy server" %s\n' "$(cat "$base/server.pub")"
  printf 'restrict,command="/usr/bin/sudo -n /usr/local/libexec/media-knowledge/deploy web" %s\n' "$(cat "$base/web.pub")"
} > /home/media-deploy/.ssh/authorized_keys
chown media-deploy:media-deploy /home/media-deploy/.ssh/authorized_keys
chmod 600 /home/media-deploy/.ssh/authorized_keys
printf '%s\n' 'media-deploy ALL=(root) NOPASSWD: /usr/local/libexec/media-knowledge/deploy server, /usr/local/libexec/media-knowledge/deploy web' > /etc/sudoers.d/media-knowledge
chmod 440 /etc/sudoers.d/media-knowledge
visudo -cf /etc/sudoers.d/media-knowledge
echo 'Deployment receiver installed. Application starts after first tagged releases.'
