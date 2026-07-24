#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "Usage: $0 /path/to/CLIProxyAPI" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
upstream_root="$(cd "$1" && pwd)"

if [[ ! -f "${upstream_root}/go.mod" || ! -d "${upstream_root}/cmd/server" ]]; then
  echo "Core upstream checkout is invalid: ${upstream_root}" >&2
  exit 1
fi

if [[ -d "${upstream_root}/.git" ]] && [[ -n "$(git -C "${upstream_root}" status --porcelain)" ]]; then
  echo "Core upstream checkout must be clean before validation: ${upstream_root}" >&2
  exit 1
fi

export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-${TMPDIR:-/tmp}/cliproxyapi-pro-pycache}"
export SRC_ROOT="${upstream_root}"

guarded_source='internal/logging/requestid.go'
preflight_log="$(mktemp "${TMPDIR:-/tmp}/cliproxyapi-pro-preflight.XXXXXX")"
printf '\n' >> "${upstream_root}/${guarded_source}"
if python3 "${repo_root}/cliproxyapi-pro-core/patches/apply_upstream_patches.py" >"${preflight_log}" 2>&1; then
  echo "Core customization unexpectedly accepted changed guarded upstream source" >&2
  exit 1
fi
if ! grep -Fq 'upstream source changed before full-file replacement' "${preflight_log}"; then
  cat "${preflight_log}" >&2
  echo "Core customization did not fail with the expected upstream-drift error" >&2
  exit 1
fi
if [[ -e "${upstream_root}/internal/embeddedusage" ]]; then
  echo "Core customization wrote files before completing preflight" >&2
  exit 1
fi
git -C "${upstream_root}" restore --worktree -- "${guarded_source}"
rm -f "${preflight_log}"
if [[ -n "$(git -C "${upstream_root}" status --porcelain)" ]]; then
  echo "Core preflight regression did not restore a clean checkout" >&2
  exit 1
fi

late_guarded_source='sdk/cliproxy/auth/scheduler.go'
python3 - "${upstream_root}/${late_guarded_source}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text()
anchor = '\t\ts.mixedCursors[cursorKey] = slot + 1\n\t\treturn picked, providerKey, nil\n'
if source.count(anchor) != 1:
    raise SystemExit(f'late Core preflight anchor count is {source.count(anchor)}, want 1')
path.write_text(source.replace(anchor, anchor.replace('return picked', 'return  picked'), 1))
PY
late_preflight_status="$(git -C "${upstream_root}" status --porcelain=v1 -uall)"
late_preflight_diff_hash="$(git -C "${upstream_root}" diff --binary | git hash-object --stdin)"
late_preflight_log="$(mktemp "${TMPDIR:-/tmp}/cliproxyapi-pro-late-preflight.XXXXXX")"
if python3 "${repo_root}/cliproxyapi-pro-core/patches/apply_upstream_patches.py" >"${late_preflight_log}" 2>&1; then
  echo "Core customization unexpectedly accepted a changed late patch anchor" >&2
  exit 1
fi
if ! grep -Fq 'expected one pattern' "${late_preflight_log}"; then
  cat "${late_preflight_log}" >&2
  echo "Core customization did not fail with the expected late-anchor error" >&2
  exit 1
fi
if [[ "$(git -C "${upstream_root}" status --porcelain=v1 -uall)" != "${late_preflight_status}" ]] || \
   [[ "$(git -C "${upstream_root}" diff --binary | git hash-object --stdin)" != "${late_preflight_diff_hash}" ]]; then
  echo "Core customization changed the source tree before validating every patch anchor" >&2
  exit 1
fi
git -C "${upstream_root}" restore --worktree -- "${late_guarded_source}"
rm -f "${late_preflight_log}"

python3 "${repo_root}/cliproxyapi-pro-core/patches/apply_upstream_patches.py"
git -C "${upstream_root}" diff --check

git -C "${upstream_root}" add -N .
patched_diff_hash="$(git -C "${upstream_root}" diff --binary | git hash-object --stdin)"
reapply_log="$(mktemp "${TMPDIR:-/tmp}/cliproxyapi-pro-reapply.XXXXXX")"
if python3 "${repo_root}/cliproxyapi-pro-core/patches/apply_upstream_patches.py" >"${reapply_log}" 2>&1; then
  echo "Core customization unexpectedly allowed a second application" >&2
  exit 1
fi
if ! grep -Fq 'target already contains CLIProxyAPI Pro customizations' "${reapply_log}"; then
  cat "${reapply_log}" >&2
  echo "Core customization did not fail with the expected already-applied error" >&2
  exit 1
fi
rm -f "${reapply_log}"
reapplied_diff_hash="$(git -C "${upstream_root}" diff --binary | git hash-object --stdin)"
if [[ "${patched_diff_hash}" != "${reapplied_diff_hash}" ]]; then
  echo "Core customization changed the source tree during rejected reapplication" >&2
  exit 1
fi

test_flags=(-count=1)
if [[ "${VALIDATION_RACE:-0}" == "1" ]]; then
  test_flags+=(-race)
fi

go -C "${upstream_root}" test "${test_flags[@]}" ./internal/embeddedusage/...
go -C "${upstream_root}" test "${test_flags[@]}" \
  ./internal/api/handlers/management \
  ./internal/pluginhost \
  ./internal/pluginstore \
  ./internal/redisqueue \
  ./sdk/cliproxy/auth

build_dir="$(mktemp -d "${TMPDIR:-/tmp}/cliproxyapi-pro-build.XXXXXX")"
trap 'rm -rf "${build_dir}"' EXIT
go -C "${upstream_root}" build -buildvcs=false -o "${build_dir}/cli-proxy-api" ./cmd/server/
