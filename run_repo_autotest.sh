#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  ./run_repo_autotest.sh <repo_url> [repo_ref] [repo_subdir]

Environment variables:
  TESTDATA_DIR   Directory containing sdcard-*.img.gz, judge_*.py, config.json.
                 Default: /root/OSKernel/testdata
  REPO_DEPTH     Optional git clone depth, for example: 1

Examples:
  ./run_repo_autotest.sh https://gitlab.eduxiji.net/group/project.git
  ./run_repo_autotest.sh https://gitlab.eduxiji.net/group/project.git main .
  REPO_DEPTH=1 ./run_repo_autotest.sh https://gitlab.eduxiji.net/group/project.git
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 1 ]]; then
    usage
    exit 0
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
KERNEL_DIR="${SCRIPT_DIR}/kernel"
KERNEL_ZIP="${SCRIPT_DIR}/kernel.zip"
TESTDATA_DIR="${TESTDATA_DIR:-/root/OSKernel/testdata}"
HOST_SHELL_BACKUP_DIR="${HOST_SHELL_BACKUP_DIR:-/root/.cache/oskernel-autotest-host-shells}"

REPO_URL="$1"
REPO_REF="${2:-${REPO_REF:-}}"
REPO_SUBDIR="${3:-${REPO_SUBDIR:-}}"
REPO_DEPTH="${REPO_DEPTH:-}"

mask_repo_url() {
    python3 - "$1" <<'PY'
from sys import argv
from urllib.parse import urlsplit, urlunsplit

url = argv[1]
try:
    parts = urlsplit(url)
except ValueError:
    print(url)
    raise SystemExit

if not parts.username and not parts.password:
    print(url)
    raise SystemExit

host = parts.hostname or ""
if parts.port:
    host = f"{host}:{parts.port}"
netloc = f"{parts.username or '***'}:***@{host}"
print(urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment)))
PY
}

is_elf() {
    python3 - "$1" <<'PY'
from pathlib import Path
from sys import argv, exit

try:
    exit(0 if Path(argv[1]).read_bytes()[:4] == b"\x7fELF" else 1)
except OSError:
    exit(1)
PY
}

restore_host_shells() {
    mkdir -p "${HOST_SHELL_BACKUP_DIR}"
    local name src backup
    for name in bash dash; do
        src="/bin/${name}"
        backup="${HOST_SHELL_BACKUP_DIR}/${name}"
        if is_elf "${src}"; then
            if [[ ! -f "${backup}" ]] || ! is_elf "${backup}"; then
                install -m 755 "${src}" "${backup}"
            fi
        elif [[ -f "${backup}" ]] && is_elf "${backup}"; then
            install -m 755 "${backup}" "${src}"
        fi
    done
}

restore_host_shells

if [[ ! -d "${KERNEL_DIR}" ]]; then
    echo "error: missing autotest kernel directory: ${KERNEL_DIR}" >&2
    exit 1
fi

if [[ ! -d "${TESTDATA_DIR}" ]]; then
    echo "error: missing TESTDATA_DIR: ${TESTDATA_DIR}" >&2
    exit 1
fi

mkdir -p /coursegrader /mnt/cghook
ln -sfn "${TESTDATA_DIR}" /coursegrader/testdata

python3 - "${KERNEL_DIR}" "${KERNEL_ZIP}" <<'PY'
from pathlib import Path
from sys import argv
from zipfile import ZipFile, ZIP_DEFLATED

kernel_dir = Path(argv[1])
kernel_zip = Path(argv[2])
if kernel_zip.exists():
    kernel_zip.unlink()

with ZipFile(kernel_zip, "w", ZIP_DEFLATED) as z:
    for path in kernel_dir.rglob("*"):
        if path.is_file():
            z.write(path, path.relative_to(kernel_dir))
PY

echo "repo_url: $(mask_repo_url "${REPO_URL}")"
[[ -n "${REPO_REF}" ]] && echo "repo_ref: ${REPO_REF}"
[[ -n "${REPO_SUBDIR}" ]] && echo "repo_subdir: ${REPO_SUBDIR}"
[[ -n "${REPO_DEPTH}" ]] && echo "repo_depth: ${REPO_DEPTH}"
echo "testdata: ${TESTDATA_DIR}"
echo "kernel: ${KERNEL_ZIP}"

export REPO_URL
export PYTHONPATH="${KERNEL_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
[[ -n "${REPO_REF}" ]] && export REPO_REF
[[ -n "${REPO_SUBDIR}" ]] && export REPO_SUBDIR
[[ -n "${REPO_DEPTH}" ]] && export REPO_DEPTH

python3 "${KERNEL_ZIP}"
