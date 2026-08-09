#!/bin/sh
set -eu

# 613-coding web delegates to uvicorn with the isolated app factory.
exec 613-coding web --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
