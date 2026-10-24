#!/bin/sh
set -eu

PUID="${PUID:-}"
PGID="${PGID:-}"
if [ -n "$PUID" ] || [ -n "$PGID" ]; then
  if [ -z "$PUID" ] || [ -z "$PGID" ]; then
    echo "PUID and PGID must be configured together" >&2
    exit 2
  fi
  case "$PUID:$PGID" in
    *[!0-9:]*|:*|*:)
      echo "PUID and PGID must be numeric" >&2
      exit 2
      ;;
  esac
fi

if [ "$(id -u)" = "0" ] && [ -n "$PUID" ] && [ "${SEED_AGENT_PRIVILEGES_DROPPED:-false}" != "true" ]; then
  if ! command -v setpriv >/dev/null 2>&1; then
    echo "setpriv is required to drop container privileges" >&2
    exit 2
  fi
  exec env \
    SEED_AGENT_PRIVILEGES_DROPPED=true \
    HOME=/tmp/seed-agent \
    setpriv \
      --reuid "$PUID" \
      --regid "$PGID" \
      --clear-groups \
      --inh-caps=-all \
      --ambient-caps=-all \
      --bounding-set=-all \
      "$0" "$@"
fi

mkdir -p "${HOME:-/tmp/seed-agent}"

if [ "${1:-}" = "seed-agent" ]; then
  shift
  if [ "${SEED_AGENT_ROLE:-seed}" != "media" ] && [ "${1:-}" != "media-worker" ]; then
    exec seed-agent "$@"
  fi
fi

case "${1:-}" in
  "")
    MODE="${SEED_AGENT_MODE:-schedule-run}"
    ;;
  -*)
    if [ "${SEED_AGENT_ROLE:-seed}" = "media" ]; then
      echo "media role requires an explicit media command" >&2
      exit 2
    fi
    exec seed-agent "$@"
    ;;
  *)
    MODE="$1"
    shift
    ;;
esac

CONFIG_PATH="${SEED_AGENT_CONFIG:-/app/config/config.yaml}"
EXECUTE="${SEED_AGENT_EXECUTE:-true}"
INTERVAL_MINUTES="${SEED_AGENT_INTERVAL_MINUTES:-}"
MIN_FREE_WINDOW_MINUTES="${SEED_AGENT_MIN_FREE_WINDOW_MINUTES:-}"
REQUIRE_KNOWN_FREE_WINDOW="${SEED_AGENT_REQUIRE_KNOWN_FREE_WINDOW:-}"
HEARTBEAT_FILE="${SEED_AGENT_HEARTBEAT_FILE:-}"
MAX_STALENESS_MINUTES="${SEED_AGENT_MAX_STALENESS_MINUTES:-}"
MAX_CYCLES="${SEED_AGENT_MAX_CYCLES:-}"
PRUNE="${SEED_AGENT_PRUNE:-}"
INTENT="${SEED_AGENT_INTENT:-}"
INTENT_EXECUTE="${SEED_AGENT_INTENT_EXECUTE:-}"
STARTUP_STATUS="${SEED_AGENT_STARTUP_STATUS:-true}"
WEB_ENABLED="${SEED_AGENT_WEB_ENABLED:-false}"
WEB_HOST="${SEED_AGENT_WEB_HOST:-0.0.0.0}"
WEB_PORT="${SEED_AGENT_WEB_PORT:-8765}"

ROLE="${SEED_AGENT_ROLE:-seed}"
if [ "$MODE" = "media-worker" ]; then
  ROLE=media
fi
case "$ROLE" in
  seed|media) ;;
  *) echo "SEED_AGENT_ROLE must be seed or media" >&2; exit 2 ;;
esac
if [ "$ROLE" = "media" ]; then
  case "$MODE" in
    media-worker|healthcheck|runtime-status) ;;
    *) echo "media role requires media-worker, healthcheck or runtime-status" >&2; exit 2 ;;
  esac
  EXPECT_ROLE=false
  for ARG in "$@"; do
    if [ "$EXPECT_ROLE" = "true" ]; then
      if [ "$ARG" != "media" ]; then
        echo "media deployment cannot select seed role diagnostics" >&2; exit 2
      fi
      EXPECT_ROLE=false
    fi
    case "$ARG" in
      --role) EXPECT_ROLE=true ;;
      --role=media) ;;
      --role=*) echo "media deployment cannot select seed role diagnostics" >&2; exit 2 ;;
    esac
  done
fi

# Prepend defaults, preserving the exact original argument boundaries.
if [ "$MODE" = "healthcheck" ] || [ "$MODE" = "runtime-status" ]; then
  set -- --role "$ROLE" "$@"
fi

case "$MODE" in
  run-once|enqueue|schedule-run)
    if [ "$EXECUTE" = "true" ]; then
      set -- --execute "$@"
    fi
    if [ -n "$MIN_FREE_WINDOW_MINUTES" ]; then
      set -- --min-free-window-minutes "$MIN_FREE_WINDOW_MINUTES" "$@"
    fi
    if [ -n "$REQUIRE_KNOWN_FREE_WINDOW" ]; then
      if [ "$REQUIRE_KNOWN_FREE_WINDOW" = "true" ]; then
        set -- --require-known-free-window "$@"
      else
        set -- --allow-unknown-free-window "$@"
      fi
    fi
    ;;
esac

if [ "$MODE" = "media-worker" ] && [ -n "$MAX_CYCLES" ]; then
  set -- --max-cycles "$MAX_CYCLES" "$@"
fi

if [ "$MODE" = "schedule-run" ]; then
  if [ -n "$HEARTBEAT_FILE" ]; then
    set -- --heartbeat-file "$HEARTBEAT_FILE" "$@"
  fi
  if [ -n "$INTERVAL_MINUTES" ]; then
    set -- --interval-minutes "$INTERVAL_MINUTES" "$@"
  fi
  if [ -n "$MAX_CYCLES" ]; then
    set -- --max-cycles "$MAX_CYCLES" "$@"
  fi
  if [ -n "$PRUNE" ]; then
    if [ "$PRUNE" = "true" ]; then
      set -- --prune "$@"
    else
      set -- --no-prune "$@"
    fi
  fi
  if [ -n "$INTENT" ]; then
    if [ "$INTENT" = "true" ]; then
      set -- --intent "$@"
    else
      set -- --no-intent "$@"
    fi
  fi
  if [ -n "$INTENT_EXECUTE" ]; then
    if [ "$INTENT_EXECUTE" = "true" ]; then
      set -- --intent-execute "$@"
    else
      set -- --intent-dry-run "$@"
    fi
  fi
fi

if [ "$MODE" = "healthcheck" ] && [ "$ROLE" = "seed" ]; then
  if [ -n "$HEARTBEAT_FILE" ]; then
    set -- --heartbeat-file "$HEARTBEAT_FILE" "$@"
  fi
  if [ -n "$MAX_STALENESS_MINUTES" ]; then
    set -- --max-staleness-minutes "$MAX_STALENESS_MINUTES" "$@"
  fi
fi

if [ "$MODE" = "web" ]; then
  set -- --host "$WEB_HOST" "$@" --port "$WEB_PORT"
fi

startup_status() {
  set -- runtime-status --config "$CONFIG_PATH" --role "$ROLE"
  if [ "$ROLE" = "seed" ] && [ -n "$HEARTBEAT_FILE" ]; then
    set -- "$@" --heartbeat-file "$HEARTBEAT_FILE"
  fi
  if [ "$ROLE" = "seed" ] && [ -n "$MAX_STALENESS_MINUTES" ]; then
    set -- "$@" --max-staleness-minutes "$MAX_STALENESS_MINUTES"
  fi
  seed-agent "$@" || true
}

if [ "$STARTUP_STATUS" = "true" ] && [ "$MODE" != "healthcheck" ]; then
  # Best effort: the primary command reports its own normal failure if invalid.
  startup_status
fi

if [ "$ROLE" = "seed" ] && [ "$WEB_ENABLED" = "true" ] && [ "$MODE" != "web" ] && [ "$MODE" != "healthcheck" ]; then
  echo "Starting seed-agent web UI at http://$WEB_HOST:$WEB_PORT"
  seed-agent web --config "$CONFIG_PATH" --host "$WEB_HOST" --port "$WEB_PORT" &
fi

exec seed-agent "$MODE" --config "$CONFIG_PATH" "$@"
