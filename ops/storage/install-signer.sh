#!/usr/bin/env bash
# Prepare the admin-only signer on an Ubuntu 24.04 x86_64 VPS without system package updates.
set -euo pipefail
target=${1:?Usage: install-signer.sh SSH_ALIAS}
[[ "$target" =~ ^[a-zA-Z0-9_@.-]+$ && "$target" != -* ]] || exit 10
base=$(cd -- "$(dirname -- "$0")" && pwd)
task_temp_dir=$(mktemp -d)
trap 'rm -rf -- "$task_temp_dir"' EXIT
python3 -m venv "$task_temp_dir/build"
"$task_temp_dir/build/bin/pip" install --target "$task_temp_dir/libs" \
  --only-binary=:all: --python-version 3.12 --platform manylinux2014_x86_64 \
  -r "$base/requirements.txt"
if [[ -n $(find "$task_temp_dir/libs" -name '*.so' -print -quit) ]]; then
  echo 'Expected pure Python dependencies' >&2
  exit 11
fi
ssh -T -o BatchMode=yes "$target" 'python3 -m venv --without-pip /opt/media-knowledge/storage-venv'
tar --exclude='__pycache__' --exclude='*.pyc' -C "$task_temp_dir/libs" -czf - . |
  ssh -T -o BatchMode=yes "$target" 'tar xzf - -C /opt/media-knowledge/storage-venv/lib/python3.12/site-packages'
ssh -T -o BatchMode=yes "$target" \
  'install -d -m 755 /usr/local/libexec/media-knowledge && install -m 755 /dev/stdin /usr/local/libexec/media-knowledge/sign-probe.py' < "$base/sign-probe.py"
ssh -T -o BatchMode=yes "$target" \
  '/opt/media-knowledge/storage-venv/bin/python -c "import boto3; print(\"S3 signer installed in isolated environment\")"'
