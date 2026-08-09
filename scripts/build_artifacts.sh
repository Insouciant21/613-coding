#!/usr/bin/env bash
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT_DIR=${1:-"$ROOT_DIR/dist"}
case "$OUT_DIR" in
  ""|/|.)
    echo "refusing unsafe artifact output directory: $OUT_DIR" >&2
    exit 2
    ;;
esac

OUT_DIR=$(CDPATH= cd -- "$(dirname -- "$OUT_DIR")" && pwd)/$(basename -- "$OUT_DIR")
BUILD_DIR="$OUT_DIR/.build"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR" "$BUILD_DIR/dist" "$BUILD_DIR/work" "$BUILD_DIR/spec"

cd "$ROOT_DIR"
uv build --out-dir "$OUT_DIR"
cp packaging/613-coding.spec "$BUILD_DIR/spec/613-coding.spec"
CODING613_ROOT="$ROOT_DIR" uv run pyinstaller --clean --noconfirm \
  --distpath "$BUILD_DIR/dist" \
  --workpath "$BUILD_DIR/work" \
  "$BUILD_DIR/spec/613-coding.spec"

test -x "$BUILD_DIR/dist/613-coding-linux-x86_64"
cp "$BUILD_DIR/dist/613-coding-linux-x86_64" "$OUT_DIR/613-coding-linux-x86_64"
rm -rf "$BUILD_DIR"

cd "$OUT_DIR"
LC_ALL=C sha256sum \
  613-coding-linux-x86_64 \
  613_coding-*.whl \
  613_coding-*.tar.gz \
  | LC_ALL=C sort > SHA256SUMS
echo "artifacts written to $OUT_DIR"
