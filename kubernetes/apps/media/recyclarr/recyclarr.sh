#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

[[ -f .env ]] && source .env

get_key() { infisical secrets get api-key --env=prod --path="/media/$1" --silent --plain; }

export SONARR_API_KEY=$(get_key sonarr)
export SONARR_ANIME_API_KEY=$(get_key sonarr-anime)
export RADARR_API_KEY=$(get_key radarr)
export RADARR_4K_API_KEY=$(get_key radarr-4k)
export RADARR_ANIME_API_KEY=$(get_key radarr-anime)

export SONARR_BASE_URL="https://sonarr.${SECRET_DOMAIN}"
export SONARR_ANIME_BASE_URL="https://sonarr-anime.${SECRET_DOMAIN}"
export RADARR_BASE_URL="https://radarr.${SECRET_DOMAIN}"
export RADARR_4K_BASE_URL="https://radarr-4k.${SECRET_DOMAIN}"
export RADARR_ANIME_BASE_URL="https://radarr-anime.${SECRET_DOMAIN}"

docker compose run --rm recyclarr "$@"
