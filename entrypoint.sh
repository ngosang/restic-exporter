#!/usr/bin/env sh

# Exit on error. For debug use set -x
set -e

if [ -n "${RESTIC_REPO_PASSWORD}" ]; then
  echo "The environment variable RESTIC_REPO_PASSWORD is deprecated, please use RESTIC_PASSWORD instead."
  export RESTIC_PASSWORD="${RESTIC_REPO_PASSWORD}"
fi
if [ -n "${RESTIC_REPO_PASSWORD_FILE}" ]; then
  echo "The environment variable RESTIC_REPO_PASSWORD_FILE is deprecated, please use RESTIC_PASSWORD_FILE instead."
  export RESTIC_PASSWORD_FILE="${RESTIC_REPO_PASSWORD_FILE}"
fi

if [ -z "${RESTIC_PASSWORD}" ]; then
  if [ -z "${RESTIC_PASSWORD_FILE}" ]; then
    echo "You have to define one of these environment variables: RESTIC_PASSWORD or RESTIC_PASSWORD_FILE"
    exit 1
  fi
else
  export RESTIC_PASSWORD_FILE="/tmp/restic_passwd"
  echo "${RESTIC_PASSWORD}" > "${RESTIC_PASSWORD_FILE}"
fi

/usr/local/bin/python -u /restic-exporter.py
