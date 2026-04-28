#!/bin/sh
set -eu

MODE="${SEED_AGENT_MODE:-schedule-run}"
CONFIG_PATH="${SEED_AGENT_CONFIG:-/config/config.yaml}"
EXECUTE="${SEED_AGENT_EXECUTE:-true}"
INTERVAL_MINUTES="${SEED_AGENT_INTERVAL_MINUTES:-60}"
MIN_FREE_WINDOW_MINUTES="${SEED_AGENT_MIN_FREE_WINDOW_MINUTES:-}"
REQUIRE_KNOWN_FREE_WINDOW="${SEED_AGENT_REQUIRE_KNOWN_FREE_WINDOW:-}"
MAX_CYCLES="${SEED_AGENT_MAX_CYCLES:-}"

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
  set -- "$@" --interval-minutes "$INTERVAL_MINUTES"
  if [ -n "$MAX_CYCLES" ]; then
    set -- "$@" --max-cycles "$MAX_CYCLES"
  fi
fi

exec "$@"
