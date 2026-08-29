#!/usr/bin/env bash
# Generate Python protobuf + gRPC stubs from air_traffic_types.proto
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GRPC_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$GRPC_DIR")"

python -m grpc_tools.protoc \
    -I "$GRPC_DIR" \
    --python_out="$GRPC_DIR/python" \
    --pyi_out="$GRPC_DIR/python" \
    --grpc_python_out="$GRPC_DIR/python" \
    "$GRPC_DIR/air_traffic_types.proto"

echo "Generated stubs in $GRPC_DIR/python/"
