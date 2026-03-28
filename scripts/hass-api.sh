#!/usr/bin/env bash

# hass-api.sh - Convenience wrapper for Home Assistant REST API calls

set -euo pipefail

if [[ -z "${SECRET_DOMAIN:-}" ]]; then
    echo "Error: SECRET_DOMAIN is not set" >&2
    exit 1
fi

if [[ -z "${HASS_TOKEN:-}" ]]; then
    echo "Error: HASS_TOKEN is not set" >&2
    exit 1
fi

HASS_URL="https://ha.${SECRET_DOMAIN}"
DEFAULT_LIMIT=20

# --- helpers ---

api_call() {
    local method="$1" path="$2" body="${3:-}"
    local -a curl_args=(
        -s -X "$method"
        -H "Authorization: Bearer ${HASS_TOKEN}"
        -H "Content-Type: application/json"
    )
    if [[ "$body" == "-" ]]; then
        curl_args+=(-d @-)
    elif [[ -n "$body" ]]; then
        curl_args+=(-d "$body")
    fi
    curl "${curl_args[@]}" "${HASS_URL}${path}"
}

# --- subcommands ---

cmd_raw() {
    if [[ $# -lt 2 ]]; then
        echo "Usage: hass-api.sh raw METHOD /api/path [json-body | -]" >&2
        exit 1
    fi
    local method
    method="$(echo "$1" | tr '[:lower:]' '[:upper:]')"
    shift
    local response
    response=$(api_call "$method" "$@")
    if echo "$response" | jq . 2>/dev/null; then
        return
    fi
    # Plain text response (e.g., /api/error_log)
    echo "$response"
}

cmd_states() {
    local domain="" limit="$DEFAULT_LIMIT"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -n) limit="$2"; shift 2 ;;
            -n*) limit="${1#-n}"; shift ;;
            --all) limit=0; shift ;;
            *) domain="$1"; shift ;;
        esac
    done

    local jq_filter
    if [[ -n "$domain" && "$domain" == *.* ]]; then
        # Full entity_id: return single entity detail
        api_call GET "/api/states/${domain}" | jq .
        return
    elif [[ -n "$domain" ]]; then
        jq_filter="[.[] | select(.entity_id | startswith(\"${domain}.\"))
            | {entity_id, state, name: .attributes.friendly_name}]"
    else
        # No domain: summary count by domain
        jq_filter='group_by(.entity_id | split(".")[0])
            | map({domain: .[0].entity_id | split(".")[0], count: length})
            | sort_by(-.count)'
    fi

    if [[ "$limit" -gt 0 ]] 2>/dev/null; then
        jq_filter="${jq_filter} | .[:${limit}]"
    fi
    api_call GET /api/states | jq "$jq_filter"
}

cmd_template() {
    if [[ $# -eq 0 ]]; then
        echo "Usage: hass-api.sh template '<jinja2 string>'" >&2
        exit 1
    fi
    local tmpl="$*"
    # Build JSON body with jq to avoid shell quoting issues
    # Template endpoint returns plain text, not JSON
    jq -n --arg t "$tmpl" '{template: $t}' \
        | api_call POST /api/template -
}

cmd_config() {
    if [[ $# -lt 1 ]]; then
        cat >&2 <<'EOF'
Usage: hass-api.sh config <type> <identifier>

Types:
  automation <entity_id|id>   Get automation config by entity_id or UUID
  script <entity_id|slug>     Get script config by entity_id or slug
EOF
        exit 1
    fi
    local type="$1" identifier="${2:-}"

    case "$type" in
        automation)
            local config_id="$identifier"
            # If given an entity_id, resolve to the UUID
            if [[ "$identifier" == automation.* ]]; then
                config_id=$(api_call GET "/api/states/${identifier}" \
                    | jq -r '.attributes.id // empty')
                if [[ -z "$config_id" ]]; then
                    echo "Error: could not resolve automation id from ${identifier}" >&2
                    exit 1
                fi
            fi
            api_call GET "/api/config/automation/config/${config_id}" | jq .
            ;;
        script)
            local slug="$identifier"
            # Strip script. prefix if present
            slug="${slug#script.}"
            api_call GET "/api/config/script/config/${slug}" | jq .
            ;;
        *)
            echo "Error: unknown config type '${type}' (use: automation, script)" >&2
            exit 1
            ;;
    esac
}

cmd_attributes() {
    if [[ $# -lt 1 ]]; then
        echo "Usage: hass-api.sh attributes <entity_id>" >&2
        exit 1
    fi
    api_call GET "/api/states/$1" | jq '.attributes'
}

cmd_orient() {
    if [[ $# -lt 1 ]]; then
        echo "Usage: hass-api.sh orient <search-term> [term2 ...]" >&2
        exit 1
    fi
    local terms="$*"

    python3 -c "
import json, re, sys, urllib.request, os

base = '${HASS_URL}'
token = os.environ['HASS_TOKEN']
terms = '''${terms}'''.split()
pattern = re.compile('|'.join(re.escape(t) for t in terms), re.IGNORECASE)

def api(path):
    req = urllib.request.Request(f'{base}{path}',
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

# 1. Find matching entities
states = api('/api/states')
matches = [s for s in states if pattern.search(s['entity_id'])
           or pattern.search(s['attributes'].get('friendly_name', ''))]

entity_ids = {s['entity_id'] for s in matches}

print('## Entities')
for s in sorted(matches, key=lambda x: x['entity_id']):
    name = s['attributes'].get('friendly_name', '')
    print(f\"  {s['entity_id']}: {s['state']}  ({name})\")

# 2. Find automations referencing any matched entity
automations = [s for s in states if s['entity_id'].startswith('automation.')]
print('\n## Automations')
found_automations = []
for a in automations:
    config_id = a['attributes'].get('id')
    if not config_id:
        continue
    try:
        config = api(f'/api/config/automation/config/{config_id}')
    except Exception:
        continue
    config_str = json.dumps(config)
    # Match if config references any matched entity or search terms
    if any(eid in config_str for eid in entity_ids) or pattern.search(config_str):
        found_automations.append((a, config))
        alias = config.get('alias', a['entity_id'])
        print(f\"\n### {alias} ({a['entity_id']}, state: {a['state']})\")
        print(json.dumps(config, indent=2))

if not found_automations:
    print('  (none found)')

# 3. Find scripts referencing any matched entity
scripts = [s for s in states if s['entity_id'].startswith('script.')]
print('\n## Scripts')
found_scripts = []
for s in scripts:
    slug = s['entity_id'].replace('script.', '')
    try:
        config = api(f'/api/config/script/config/{slug}')
    except Exception:
        continue
    config_str = json.dumps(config)
    if any(eid in config_str for eid in entity_ids) or pattern.search(config_str):
        found_scripts.append((s, config))
        alias = config.get('alias', s['entity_id'])
        print(f\"\n### {alias} ({s['entity_id']})\")
        print(json.dumps(config, indent=2))

if not found_scripts:
    print('  (none found)')
"
}

cmd_entity() {
    if [[ $# -lt 2 ]]; then
        cat >&2 <<'EOF'
Usage: hass-api.sh entity <action> <entity_id>

Actions:
  enable <entity_id>    Enable a disabled entity
  disable <entity_id>   Disable an entity
EOF
        exit 1
    fi
    local action="$1" entity_id="$2"
    local disabled_by

    case "$action" in
        enable)  disabled_by="None" ;;
        disable) disabled_by="\"user\"" ;;
        *)
            echo "Error: unknown action '${action}' (use: enable, disable)" >&2
            exit 1
            ;;
    esac

    python3 -c "
import asyncio, json, os, aiohttp

async def main():
    url = 'wss://ha.${SECRET_DOMAIN}/api/websocket'
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url) as ws:
            await ws.receive_json()
            await ws.send_json({'type': 'auth', 'access_token': os.environ['HASS_TOKEN']})
            msg = await ws.receive_json()
            if msg['type'] != 'auth_ok':
                print(json.dumps(msg), flush=True)
                return
            await ws.send_json({
                'id': 1,
                'type': 'config/entity_registry/update',
                'entity_id': '${entity_id}',
                'disabled_by': ${disabled_by}
            })
            msg = await ws.receive_json()
            if msg.get('success'):
                entry = msg['result']['entity_entry']
                delay = msg['result'].get('reload_delay')
                status = 'disabled' if entry.get('disabled_by') else 'enabled'
                print(f\"{entry['entity_id']}: {status}\")
                if delay:
                    print(f'Reload in {delay}s')
            else:
                print(json.dumps(msg, indent=2))

asyncio.run(main())
"
}

# --- dispatch ---

usage() {
    cat >&2 <<'EOF'
Usage: hass-api.sh <command> [args]

Commands:
  raw METHOD /api/path [body|-]   Direct API call (body: JSON string or - for stdin)
  states [domain] [-n N|--all]    List entities (no arg: domain summary)
  template '<jinja2>'             Render a Jinja2 template (handles quoting)
  config automation <id>          Get automation config YAML
  config script <slug>            Get script config YAML
  attributes <entity_id>          Show entity attributes
  entity enable|disable <id>      Enable/disable entity (WebSocket, needs aiohttp)
  orient <term> [term2 ...]       Discover entities, automations, and scripts matching terms

Examples:
  hass-api.sh states                          Domain summary
  hass-api.sh states light                    List lights (default: 20)
  hass-api.sh states light -n 5               List 5 lights
  hass-api.sh states sensor.temperature       Single entity detail
  hass-api.sh template '{{ states("sensor.temperature") }}'
  hass-api.sh config automation automation.jvc_hdr_pm_automation
  hass-api.sh config script script.set_expected_picture_modes
  hass-api.sh attributes remote.harmony_media_room
  hass-api.sh raw GET /api/services
  hass-api.sh raw POST /api/services/light/turn_on '{"entity_id":"light.office"}'
  echo '{"entity_id":"light.office"}' | hass-api.sh raw POST /api/services/light/turn_on -
  hass-api.sh entity enable sensor.jvc_projector_hdr_mode
  hass-api.sh entity disable sensor.some_entity
  hass-api.sh orient jvc nz7 projector
  hass-api.sh orient pool
  hass-api.sh orient "media room"
EOF
    exit 1
}

if [[ $# -eq 0 ]]; then
    usage
fi

command="$1"
shift

case "$command" in
    raw)        cmd_raw "$@" ;;
    states)     cmd_states "$@" ;;
    template)   cmd_template "$@" ;;
    config)     cmd_config "$@" ;;
    attributes) cmd_attributes "$@" ;;
    entity)     cmd_entity "$@" ;;
    orient)     cmd_orient "$@" ;;
    -h|--help)  usage ;;
    *)          usage ;;
esac
