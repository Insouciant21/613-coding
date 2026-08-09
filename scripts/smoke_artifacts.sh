#!/usr/bin/env bash
set -eu

DIST_DIR=${1:?usage: smoke_artifacts.sh DIST_DIR}
DIST_DIR=$(CDPATH= cd -- "$DIST_DIR" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BINARY="$DIST_DIR/613-coding-linux-x86_64"
WHEEL=$(find "$DIST_DIR" -maxdepth 1 -type f -name '613_coding-*.whl' -print -quit)
SDIST=$(find "$DIST_DIR" -maxdepth 1 -type f -name '613_coding-*.tar.gz' -print -quit)

test -n "$WHEEL"
test -n "$SDIST"
test -x "$BINARY"
test -f "$DIST_DIR/SHA256SUMS"
(cd "$DIST_DIR" && sha256sum -c SHA256SUMS)

HELP_FILE=$(mktemp)
TEMP_DIR=$(mktemp -d)
cleanup() {
  rm -f "$HELP_FILE"
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

"$BINARY" --help > "$HELP_FILE"
mkdir -p "$TEMP_DIR/binary-repo" "$TEMP_DIR/wheel-repo"
"$BINARY" config check --repo "$TEMP_DIR/binary-repo" >/dev/null
"$BINARY" demo core --repo "$TEMP_DIR/binary-repo" --json >/dev/null

uv venv "$TEMP_DIR/venv" >/dev/null
uv pip install --python "$TEMP_DIR/venv/bin/python" "$WHEEL" >/dev/null
"$TEMP_DIR/venv/bin/613-coding" --help > "$TEMP_DIR/wheel-help"
"$TEMP_DIR/venv/bin/613-coding" config check --repo "$TEMP_DIR/wheel-repo" >/dev/null
"$TEMP_DIR/venv/bin/613-coding" demo core --repo "$TEMP_DIR/wheel-repo" --json >/dev/null
cmp -s "$HELP_FILE" "$TEMP_DIR/wheel-help"
echo "artifact smoke passed"
