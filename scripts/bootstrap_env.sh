#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
DEFAULT_PYTHON_BIN="python3.11"
if ! command -v "${DEFAULT_PYTHON_BIN}" >/dev/null 2>&1; then
  DEFAULT_PYTHON_BIN="python3"
fi
PYTHON_BIN="${PYTHON_BIN:-${DEFAULT_PYTHON_BIN}}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Python binary not found: ${PYTHON_BIN}" >&2
  exit 1
fi

echo "Using Python: $(${PYTHON_BIN} --version)"
echo "Project root: ${ROOT_DIR}"

if [ -d "${VENV_DIR}" ]; then
  VENV_PY_VERSION="$("${VENV_DIR}/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  TARGET_PY_VERSION="$("${PYTHON_BIN}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [ "${VENV_PY_VERSION}" != "${TARGET_PY_VERSION}" ]; then
    echo "Recreating venv: ${VENV_PY_VERSION} -> ${TARGET_PY_VERSION}"
    rm -rf "${VENV_DIR}"
  fi
fi

if [ ! -d "${VENV_DIR}" ]; then
  echo "Creating shared virtual environment at ${VENV_DIR}"
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
else
  echo "Shared virtual environment already exists at ${VENV_DIR}"
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade pip wheel setuptools

# Compatibility shim for pygooglenews dependency chain on modern Python.
"${VENV_DIR}/bin/pip" install "setuptools<58"
"${VENV_DIR}/bin/pip" install --no-build-isolation "feedparser==5.2.1"
"${VENV_DIR}/bin/pip" install --upgrade setuptools

"${VENV_DIR}/bin/pip" install -r "${ROOT_DIR}/requirements-dev.txt"

echo
echo "Environment ready."
echo "Activate with:"
echo "  source ${VENV_DIR}/bin/activate"
