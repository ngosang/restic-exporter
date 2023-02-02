#!/usr/bin/env sh

# Exit on error. For debug use set -x
set -e

if [ -z "${RESTIC_REPO_PASSWORD}" ]; then
  if [ -z "${RESTIC_REPO_PASSWORD_FILE}" ]; then
    echo "You have to define one of these environment variables: RESTIC_REPO_PASSWORD or RESTIC_REPO_PASSWORD_FILE"
    exit 1
  fi
else
  export RESTIC_REPO_PASSWORD_FILE="/tmp/restic_passwd"
  echo "${RESTIC_REPO_PASSWORD}" > "${RESTIC_REPO_PASSWORD_FILE}"
fi

/usr/local/bin/python -u /restic-exporter.py
