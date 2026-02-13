#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPECTED_PREFIX="${ROOT_DIR}/.venv"

if [ -z "${VIRTUAL_ENV:-}" ]; then
  echo "No active virtualenv. Expected: ${EXPECTED_PREFIX}" >&2
  exit 1
fi

if [ "${VIRTUAL_ENV}" != "${EXPECTED_PREFIX}" ]; then
  echo "Wrong virtualenv: ${VIRTUAL_ENV}" >&2
  echo "Expected: ${EXPECTED_PREFIX}" >&2
  exit 1
fi

echo "Virtualenv OK: ${VIRTUAL_ENV}"
python --version
pip --version
