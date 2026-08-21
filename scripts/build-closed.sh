#!/usr/bin/env bash
set -e
TAG=${1:-closed}
REG=${REG:-ghcr.io/awesome56/qa-agent}
echo "Building closed image $REG:$TAG (no .py source)..."
docker build -f Dockerfile.closed -t $REG:$TAG .
echo "Verifying no .py inside..."
docker run --rm $REG:$TAG sh -c "find /app/app -name '*.py' 2>/dev/null | head; echo '--- file count:'; find /app/app -type f | wc -l"
echo "OK: $REG:$TAG ready to push"
echo "Push with: docker push $REG:$TAG"
