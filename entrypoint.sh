#!/usr/bin/env sh

# Exit on error. For debug use set -x
set -e

export PASSWORD_FILE="/tmp/restic_passwd"

if [ -z "${RESTIC_REPO_PASSWORD}" ]; then
  if [ -z "${RESTIC_REPO_PASSWORD_FILE}" ]; then
    echo "You have to define one of these environment variables: RESTIC_REPO_PASSWORD or RESTIC_REPO_PASSWORD_FILE"
    exit 1
  else
    cp "${RESTIC_REPO_PASSWORD_FILE}" "${PASSWORD_FILE}"
  fi
else
  echo "${RESTIC_REPO_PASSWORD}" > "${PASSWORD_FILE}"
fi

/usr/local/bin/python -u /restic-exporter.py
