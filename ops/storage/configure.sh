#!/usr/bin/env bash
set -euo pipefail
: "${S3_BUCKET:?Set S3_BUCKET}"
: "${WEB_ORIGIN:?Set exact HTTPS WEB_ORIGIN}"
[[ "$WEB_ORIGIN" =~ ^https://[a-zA-Z0-9.-]+(:[0-9]+)?$ ]] || { echo 'WEB_ORIGIN must be an exact HTTPS origin' >&2; exit 1; }
# Requires an authenticated yc profile and an existing dedicated private bucket.
acl_args=(--acl private)
if [[ -n "${S3_SERVICE_ACCOUNT_ID:-}" ]]; then
  : "${S3_OWNER_ID:?Set S3_OWNER_ID to preserve owner administration}"
  acl_args=(
    --grants "grantee-id=$S3_OWNER_ID,grant-type=grant-type-account,permission=permission-full-control"
    --grants "grantee-id=$S3_SERVICE_ACCOUNT_ID,grant-type=grant-type-account,permission=permission-read"
    --grants "grantee-id=$S3_SERVICE_ACCOUNT_ID,grant-type=grant-type-account,permission=permission-write"
  )
fi
profile_args=()
if [[ -n "${YC_PROFILE:-}" ]]; then
  profile_args=(--profile "$YC_PROFILE")
fi
yc storage bucket update "$S3_BUCKET" "${profile_args[@]}" \
  "${acl_args[@]}" --public-read=false --public-list=false --public-config-read=false \
  --max-size "${S3_MAX_BYTES:-1099511627776}" \
  --versioning versioning-enabled \
  --cors "allowed-origins=[$WEB_ORIGIN],allowed-methods=[method-get,method-head,method-put,method-post,method-delete],allowed-headers=[*],expose-headers=[ETag,Content-Range,Accept-Ranges],max-age-seconds=600" \
  --lifecycle-rules-from-file "$(dirname "$0")/lifecycle.json" \
  --format json > /dev/null
echo 'Private bucket configured. Old object versions are retained.'
