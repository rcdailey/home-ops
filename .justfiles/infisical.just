set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

[private]
default:
    @just --list infisical

[doc('Add a secret to Infisical with automatic folder creation')]
add-secret path value:
    #!/usr/bin/env bash
    set -euo pipefail

    FULL_PATH="{{path}}"
    SECRET_VALUE="{{value}}"

    # Extract secret name and folder path
    SECRET_NAME=$(basename "$FULL_PATH")
    FOLDER_PATH=$(dirname "$FULL_PATH")

    # Normalize paths
    FOLDER_PATH="${FOLDER_PATH#/}"
    FOLDER_PATH="${FOLDER_PATH%/}"
    SECRET_PATH="/$FOLDER_PATH"

    echo "Creating folder hierarchy for: $FOLDER_PATH"

    # Build path incrementally and create folders
    CURRENT_PATH=""
    IFS='/' read -ra SEGMENTS <<< "$FOLDER_PATH"

    for SEGMENT in "${SEGMENTS[@]}"; do
        [ -z "$SEGMENT" ] && continue

        PARENT_PATH="$CURRENT_PATH"
        if [ -z "$CURRENT_PATH" ]; then
            CURRENT_PATH="$SEGMENT"
        else
            CURRENT_PATH="$CURRENT_PATH/$SEGMENT"
        fi

        # Check if folder exists
        PARENT_FOLDERS=$(infisical secrets folders get --path "$PARENT_PATH" --env prod --silent 2>/dev/null || true)
        if ! echo "$PARENT_FOLDERS" | rg -q "│ $SEGMENT "; then
            echo "Creating folder: $CURRENT_PATH"
            if [ -z "$PARENT_PATH" ]; then
                infisical secrets folders create --name "$SEGMENT" --env prod
            else
                infisical secrets folders create --name "$SEGMENT" --path "$PARENT_PATH" --env prod
            fi
        else
            echo "Folder exists: $CURRENT_PATH"
        fi
    done

    # Set the secret
    echo "Setting secret: $SECRET_NAME at path: $SECRET_PATH"
    infisical secrets set "$SECRET_NAME=$SECRET_VALUE" --path "$SECRET_PATH" --env prod
    echo "Successfully created secret: $SECRET_NAME at path: $SECRET_PATH"

# Values never leave Infisical: the API is asked to hide them and only key paths are printed.
[doc('List secret key paths (never values) under PATH, recursively; filter by smart-case REGEX')]
list $path="/" $pattern="":
    #!/usr/bin/env bash
    set -euo pipefail
    just ensure-login
    folder="/${path#/}"
    [[ "$folder" == "/" ]] || folder="${folder%/}"
    project=$(yq '.["secrets-management"]["project-id"]' "$(git rev-parse --show-toplevel)/.infisical.yaml")
    token=$(infisical user get token --plain --silent)
    response=$(printf 'Authorization: Bearer %s' "$token" | curl -sS --fail-with-body -G -H @- \
        https://app.infisical.com/api/v3/secrets/raw \
        --data-urlencode "workspaceId=$project" \
        --data-urlencode environment=prod \
        --data-urlencode "secretPath=$folder" \
        --data-urlencode recursive=true \
        --data-urlencode viewSecretValue=false \
        --data-urlencode include_imports=false \
        --data-urlencode expandSecretReferences=false) || {
        jq -r '.message // .' <<<"$response" >&2
        exit 1
    }
    # Output matches ExternalSecret remoteRef keys, e.g. /media/qui/session-secret
    paths=$(jq -r '.secrets[] | (.secretPath | rtrimstr("/")) + "/" + .secretKey' <<<"$response" | sort)
    if [[ -n "$pattern" ]]; then
        paths=$(rg -NS -- "$pattern" <<<"$paths" || true)
    fi
    count=$(rg -c . <<<"$paths" || echo 0)
    [[ "$count" == 0 ]] || echo "$paths"
    echo "[info] $count secret(s) under $folder${pattern:+ matching $pattern}" >&2

[doc('Delete one or more secrets by full key path, e.g. /media/qui/session-secret')]
delete +$paths:
    #!/usr/bin/env bash
    set -euo pipefail
    just ensure-login
    for full in $paths; do
        infisical secrets delete "$(basename "$full")" --path "$(dirname "$full")" --env prod \
            --type shared --silent
        echo "[info] Deleted $full"
    done

[doc('Get a secret value from Infisical')]
get-secret path:
    #!/usr/bin/env bash
    set -euo pipefail

    FULL_PATH="{{path}}"
    SECRET_NAME=$(basename "$FULL_PATH")
    FOLDER_PATH=$(dirname "$FULL_PATH")

    # Normalize path
    FOLDER_PATH="${FOLDER_PATH#/}"
    FOLDER_PATH="${FOLDER_PATH%/}"
    SECRET_PATH="/$FOLDER_PATH"

    infisical secrets get "$SECRET_NAME" --path "$SECRET_PATH" --env prod --silent --plain
