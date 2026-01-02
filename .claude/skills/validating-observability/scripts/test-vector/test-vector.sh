#!/usr/bin/env bash
set -euo pipefail

# Vector Configuration Testing Script
# Provides local validation and runtime testing of Vector configurations
#
# Purpose: UX wrapper around Docker commands for testing Vector pipelines locally
# - NO complex routing logic - defers to vector.yaml configuration
# - Both K8s and local container use identical vector.yaml + VRL files
# - Simply bind-mounts config and pipes logs through Vector's pipeline
#
# Usage:
#   ./test-vector.sh start <config-dir>  # Start detached container with config
#   ./test-vector.sh test <app-name> <log>  # Send log through pipeline
#   ./test-vector.sh test <json-event>   # Send full JSON event through pipeline
#   ./test-vector.sh stop                # Stop and remove container
#   ./test-vector.sh status              # Check container status

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yaml"
CONTAINER_NAME="vector-test"
STATE_FILE="/tmp/vector-test-state"

# ANSI color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

error() {
    echo -e "${RED}Error: $1${RESET}" >&2
    exit 1
}

info() {
    echo -e "${CYAN}$1${RESET}"
}

section() {
    echo -e "\n${BOLD}${BLUE}=== $1 ===${RESET}"
}

highlight() {
    echo -e "${YELLOW}$1${RESET}"
}

# Check if container is running
is_running() {
    docker compose -f "$COMPOSE_FILE" ps --status running --format json | grep -q "\"Name\":\"${CONTAINER_NAME}\""
}

cmd_start() {
    # Stop existing container if running
    if is_running; then
        info "Stopping existing container..."
        docker compose -f "$COMPOSE_FILE" down >/dev/null 2>&1 || true
    fi

    info "Starting Vector container with docker compose..."
    docker compose -f "$COMPOSE_FILE" up -d

    # Save state
    echo "started" > "$STATE_FILE"

    # Wait for Vector to start
    sleep 2

    if ! is_running; then
        info "Container logs:"
        docker compose -f "$COMPOSE_FILE" logs
        docker compose -f "$COMPOSE_FILE" down >/dev/null 2>&1 || true
        error "Container failed to start"
    fi

    info "Container started successfully: $CONTAINER_NAME"
    info "Use '$0 test <log-string>' to test log processing"
    info "Use '$0 stop' to stop the container"
}

cmd_test() {
    local arg1="${1:-}"
    local arg2="${2:-}"

    if [[ -z "$arg1" ]]; then
        error "Usage: $0 test <app-name> <raw-log-message>
       $0 test <json-event>

Examples:
  # Simple: app name + raw log (simulates kubernetes_logs enrichment)
  $0 test cloudflare-tunnel \"2025-10-21T21:06:27Z WRN Serve tunnel error...\"

  # Advanced: full JSON event with custom metadata
  $0 test '{\"message\": \"log\", \"kubernetes\": {\"pod_labels\": {\"app.kubernetes.io/name\": \"test\"}}}'"
    fi

    # Auto-start container if not running
    if ! is_running; then
        info "Container not running, starting..."
        cmd_start
        echo ""
    fi

    local json_event

    # Detect usage pattern: app-name + message or JSON
    if [[ -n "$arg2" ]]; then
        # Pattern 1: app-name + raw log message
        local app_name="$arg1"
        local raw_message="$arg2"

        # Simulate kubernetes_logs source enrichment
        # Use jq to properly JSON-encode the message (handles quotes, newlines, etc.)
        json_event=$(jq -n \
            --arg msg "$raw_message" \
            --arg app "$app_name" \
            '{
                message: $msg,
                stream: "stdout",
                kubernetes: {
                    pod_name: ($app + "-test-12345-abcde"),
                    pod_namespace: "default",
                    container_name: "app",
                    pod_labels: {
                        "app.kubernetes.io/name": $app
                    }
                }
            }')
    else
        # Pattern 2: Full JSON event
        json_event="$arg1"

        # Validate JSON
        if ! echo "$json_event" | jq empty 2>/dev/null; then
            error "Invalid JSON event. Use 'app-name message' or valid JSON."
        fi
    fi

    section "Input"
    if [[ -n "$arg2" ]]; then
        echo -e "${DIM}App:${RESET}     ${GREEN}$arg1${RESET}"
        echo -e "${DIM}Message:${RESET} ${YELLOW}$arg2${RESET}"
    else
        echo -e "${DIM}JSON Event:${RESET}"
        echo "$json_event" | jq -C . 2>/dev/null || echo "$json_event"
    fi

    # Compact JSON to NDJSON format (Vector expects one JSON per line)
    local compact_json
    compact_json=$(echo "$json_event" | jq -c .) || error "Failed to compact JSON"

    section "Pipeline Processing"
    echo -e "${DIM}# Sending event through Vector pipeline (filters → transforms → output)${RESET}\n"

    # Get current log position to filter only new output
    local log_lines_before
    log_lines_before=$(docker compose -f "$COMPOSE_FILE" logs 2>&1 | wc -l)

    # Send event to Vector's stdin via /proc/1/fd/0 (stdin of PID 1)
    docker compose -f "$COMPOSE_FILE" exec -T vector sh -c "echo '$compact_json' > /proc/1/fd/0" 2>/dev/null || {
        error "Failed to send event to Vector stdin"
    }

    # Wait for Vector to process
    sleep 0.5

    # Capture only new log lines (console sink output)
    local pipeline_output
    pipeline_output=$(docker compose -f "$COMPOSE_FILE" logs 2>&1 | \
        tail -n +$((log_lines_before + 1)) | \
        grep -v "^2025-" | \
        grep "{" | \
        tail -1 | \
        sed 's/^vector-test  | //')

    if [[ -z "$pipeline_output" ]]; then
        info "No output captured. Showing recent container logs:"
        docker compose -f "$COMPOSE_FILE" logs --tail 15
        error "No transformed output received from Vector pipeline"
    fi

    section "Transformed Output"
    # Pretty-print the JSON output from console sink
    echo "$pipeline_output" | jq -C . 2>/dev/null || echo "$pipeline_output"
}

cmd_stop() {
    if ! is_running; then
        info "Container not running"
        rm -f "$STATE_FILE"
        return 0
    fi

    info "Stopping container..."
    docker compose -f "$COMPOSE_FILE" down
    rm -f "$STATE_FILE"
    info "Container stopped and removed"
}

cmd_status() {
    if is_running; then
        info "Container '$CONTAINER_NAME' is running"
        info ""
        info "Recent logs:"
        docker compose -f "$COMPOSE_FILE" logs --tail 10
    else
        info "Container '$CONTAINER_NAME' is not running"
        if [[ -f "$STATE_FILE" ]]; then
            rm -f "$STATE_FILE"
        fi
    fi
}

# Main command dispatcher
case "${1:-}" in
    start)
        cmd_start
        ;;
    test)
        cmd_test "${2:-}" "${3:-}"
        ;;
    stop)
        cmd_stop
        ;;
    status)
        cmd_status
        ;;
    *)
        cat <<EOF
Vector Configuration Testing Script

Usage:
  $0 start                Start Vector container with docker compose
  $0 test <log-string>    Send log through running container
  $0 stop                 Stop and remove container
  $0 status               Check container status

Examples:
  $0 start
  $0 test cloudflare-tunnel "2025-10-22T01:06:54Z ERR Request failed"
  $0 test '{"message": "test log", "kubernetes": {"pod_labels": {"app.kubernetes.io/name": "test"}}}'
  $0 stop
EOF
        exit 1
        ;;
esac
