#!/bin/sh
set -eu

image=${1:?usage: smoke_container.sh IMAGE}
name="613-coding-smoke-${GITHUB_RUN_ID:-${CI_PIPELINE_ID:-local}}-$$"

cleanup() {
    docker rm -f "$name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run -d \
    --name "$name" \
    --health-interval 1s \
    --health-timeout 3s \
    --health-start-period 1s \
    --health-retries 10 \
    "$image" >/dev/null

attempt=0
status=starting
while [ "$attempt" -lt 30 ]; do
    status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$name" 2>/dev/null || true)
    case "$status" in
        healthy) break ;;
        unhealthy | exited | dead)
            docker logs "$name" >&2 || true
            exit 1
            ;;
    esac
    attempt=$((attempt + 1))
    sleep 1
done

if [ "$status" != healthy ]; then
    docker logs "$name" >&2 || true
    echo "container did not become healthy within 30 seconds" >&2
    exit 1
fi

configured_user=$(docker inspect --format '{{.Config.User}}' "$name")
if [ "$configured_user" != coding ]; then
    echo "container configured user is '$configured_user', expected 'coding'" >&2
    exit 1
fi

echo "container smoke passed: health=healthy user=coding"
