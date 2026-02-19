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
