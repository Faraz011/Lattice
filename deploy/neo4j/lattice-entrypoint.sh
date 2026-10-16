#!/bin/bash
set -euo pipefail

if [[ -z "${NEO4J_AUTH:-}" ]]; then
  if [[ -z "${LATTICE_NEO4J_PASSWORD:-}" ]]; then
    echo "set LATTICE_NEO4J_PASSWORD (or NEO4J_AUTH)" >&2
    exit 1
  fi
  export NEO4J_AUTH="neo4j/${LATTICE_NEO4J_PASSWORD}"
fi
exec /startup/docker-entrypoint.sh "$@"
