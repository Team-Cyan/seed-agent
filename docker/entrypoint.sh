#!/bin/sh
set -eu

if [ "${1:-}" = "seed-agent" ]; then
  shift
  exec seed-agent "$@"
fi

case "${1:-}" in
  "")
    MODE="${SEED_AGENT_MODE:-schedule-run}"
    EXTRA_ARGS=""
    ;;
  -*)
    exec seed-agent "$@"
    ;;
  *)
    MODE="$1"
    shift
    EXTRA_ARGS="$*"
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

set -- seed-agent "$MODE" --config "$CONFIG_PATH"

case "$MODE" in
  run-once|enqueue|schedule-run)
    if [ "$EXECUTE" = "true" ]; then
      set -- "$@" --execute
    fi
    if [ -n "$MIN_FREE_WINDOW_MINUTES" ]; then
      set -- "$@" --min-free-window-minutes "$MIN_FREE_WINDOW_MINUTES"
    fi
    if [ -n "$REQUIRE_KNOWN_FREE_WINDOW" ]; then
      if [ "$REQUIRE_KNOWN_FREE_WINDOW" = "true" ]; then
        set -- "$@" --require-known-free-window
      else
        set -- "$@" --allow-unknown-free-window
      fi
    fi
    ;;
esac

if [ "$MODE" = "schedule-run" ]; then
  if [ -n "$HEARTBEAT_FILE" ]; then
    set -- "$@" --heartbeat-file "$HEARTBEAT_FILE"
  fi
  if [ -n "$INTERVAL_MINUTES" ]; then
    set -- "$@" --interval-minutes "$INTERVAL_MINUTES"
  fi
  if [ -n "$MAX_CYCLES" ]; then
    set -- "$@" --max-cycles "$MAX_CYCLES"
  fi
  if [ -n "$PRUNE" ]; then
    if [ "$PRUNE" = "true" ]; then
      set -- "$@" --prune
    else
      set -- "$@" --no-prune
    fi
  fi
  if [ -n "$INTENT" ]; then
    if [ "$INTENT" = "true" ]; then
      set -- "$@" --intent
    else
      set -- "$@" --no-intent
    fi
  fi
  if [ -n "$INTENT_EXECUTE" ]; then
    if [ "$INTENT_EXECUTE" = "true" ]; then
      set -- "$@" --intent-execute
    else
      set -- "$@" --intent-dry-run
    fi
  fi
fi

if [ "$MODE" = "healthcheck" ]; then
  if [ -n "$HEARTBEAT_FILE" ]; then
    set -- "$@" --heartbeat-file "$HEARTBEAT_FILE"
  fi
  if [ -n "$MAX_STALENESS_MINUTES" ]; then
    set -- "$@" --max-staleness-minutes "$MAX_STALENESS_MINUTES"
  fi
fi

if [ "$MODE" = "web" ]; then
  set -- "$@" --host "$WEB_HOST" --port "$WEB_PORT"
fi

if [ "$STARTUP_STATUS" = "true" ] && [ "$MODE" != "healthcheck" ]; then
  STATUS_ARGS="runtime-status --config $CONFIG_PATH"
  if [ -n "$HEARTBEAT_FILE" ]; then
    STATUS_ARGS="$STATUS_ARGS --heartbeat-file $HEARTBEAT_FILE"
  fi
  if [ -n "$MAX_STALENESS_MINUTES" ]; then
    STATUS_ARGS="$STATUS_ARGS --max-staleness-minutes $MAX_STALENESS_MINUTES"
  fi
  # Keep startup diagnostics best-effort so a broken config still reaches the
  # real command and produces its normal failure/log behavior.
  # shellcheck disable=SC2086
  seed-agent $STATUS_ARGS || true
fi

if [ "$WEB_ENABLED" = "true" ] && [ "$MODE" != "web" ] && [ "$MODE" != "healthcheck" ]; then
  echo "Starting seed-agent web UI at http://$WEB_HOST:$WEB_PORT"
  seed-agent web --config "$CONFIG_PATH" --host "$WEB_HOST" --port "$WEB_PORT" &
fi

# Allow explicit `docker run seed-agent:local <mode> <extra args>` overrides for
# one-off debugging while preserving env-driven Compose defaults.
if [ -n "$EXTRA_ARGS" ]; then
  # shellcheck disable=SC2086
  set -- "$@" $EXTRA_ARGS
fi

exec "$@"
