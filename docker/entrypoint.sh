#!/bin/sh
set -eu

# coding-harness web delegates to uvicorn with the isolated app factory.
exec coding-harness web --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
