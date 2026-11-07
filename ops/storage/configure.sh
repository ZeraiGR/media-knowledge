#!/usr/bin/env bash
set -euo pipefail
: "${S3_BUCKET:?Set S3_BUCKET}"
: "${WEB_ORIGIN:?Set exact HTTPS WEB_ORIGIN}"
[[ "$WEB_ORIGIN" =~ ^https://[a-zA-Z0-9.-]+(:[0-9]+)?$ ]] || { echo 'WEB_ORIGIN must be an exact HTTPS origin' >&2; exit 1; }
# Requires an authenticated yc profile and an existing dedicated private bucket.
yc storage bucket update "$S3_BUCKET" \
  --acl private --public-read=false --public-list=false --public-config-read=false \
  --max-size "${S3_MAX_BYTES:-10737418240}" \
  --versioning versioning-enabled \
  --cors "allowed-origins=[$WEB_ORIGIN],allowed-methods=[method-get,method-head,method-put,method-post,method-delete],allowed-headers=[*],expose-headers=[ETag,Content-Range,Accept-Ranges],max-age-seconds=600" \
  --lifecycle-rules-from-file "$(dirname "$0")/lifecycle.json" \
  --format json > /dev/null
echo 'Private bucket configured. Old object versions are retained.'
