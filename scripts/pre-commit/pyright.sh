#!/usr/bin/env bash
# Type-check Python files with pyright against the environment each file actually runs in:
# - files inside a uv project (nearest pyproject.toml) use that project's synced venv
# - PEP 723 scripts use their uv-managed script environment
# - other files use the environment of the single PEP 723 script beside them (e.g. its tests),
#   falling back to the hook's own interpreter
set -euo pipefail

declare -A groups=()

script_python() {
  uv sync --quiet --script "$1"
  uv python find --script "$1"
}

sibling_script() {
  local dir=$1 matches
  mapfile -t matches < <(rg -l '^# /// script' --glob '*.py' --max-depth 1 "$dir" || true)
  ((${#matches[@]} == 1)) && printf '%s\n' "${matches[0]}"
}

for file in "$@"; do
  dir=$(dirname "$file")
  project=$dir
  while [[ $project != . && ! -f $project/pyproject.toml ]]; do
    project=$(dirname "$project")
  done

  if [[ -f $project/pyproject.toml ]]; then
    groups["project:$project"]+="$file"$'\n'
  elif rg -q '^# /// script' "$file"; then
    groups["script:$file"]+="$file"$'\n'
  elif sibling=$(sibling_script "$dir"); then
    groups["script:$sibling"]+="$file"$'\n'
  else
    groups["default:"]+="$file"$'\n'
  fi
done

status=0
for key in "${!groups[@]}"; do
  kind=${key%%:*}
  target=${key#*:}
  case $kind in
    project)
      uv sync --quiet --project "$target"
      python=$target/.venv/bin/python
      ;;
    script) python=$(script_python "$target") ;;
    default) python=$(command -v python) ;;
  esac
  mapfile -t files <<<"${groups[$key]%$'\n'}"
  pyright --pythonpath "$python" "${files[@]}" || status=1
done
exit "$status"
