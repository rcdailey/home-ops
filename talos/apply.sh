#!/usr/bin/env bash
# Hands-free `topf apply`: summarize pending changes for every node, confirm once, then let topf
# apply one node at a time without per-node prompts. Run through `just talos apply`, which
# injects the Infisical secrets and runs from talos/.
#
# The summary compares documents by kind and name, so topf's document reordering, which floods
# its text diff, does not show up. Empty lists are ignored because Talos omits them when storing.
set -euo pipefail

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
log=$(mktemp --tmpdir topf-dry-run.XXXXXX.log)

# Map each document to "<kind>[/<name>]"; the legacy v1alpha1 document has no kind.
index() {
    yq ea -o=json '[.]' "$1" | jq '
        map({key: ((.kind // "v1alpha1") + (if .name then "/\(.name)" else "" end)), value: .})
        | from_entries
        | walk(if type == "object" then with_entries(select(.value != [])) else . end)'
}

# Exit code 2 means "changes detected"; anything else is a real failure.
rc=0
topf apply --dry-run >"$log" 2>&1 || rc=$?
if ((rc != 0 && rc != 2)); then
    cat "$log" >&2
    exit "$rc"
fi

# Talos reports per node, after "Dry run summary:", whether applying needs a reboot.
reboot_mode() {
    awk -v host="$1" '
        /msg="dry-run apply"/ { current = ($0 ~ ("node=" host "( |$)")) }
        current && found { print; exit }
        current && /Dry run summary:/ { found = 1 }' "$log" |
        sed -E 's/^ +//'
}

topf render -o "$work" >/dev/null 2>&1
pending=0
echo "Pending Talos config changes (+ added, - removed, ~ changed):"
for host in $(yq '.nodes[].host' topf.yaml); do
    ip=$(HOST="$host" yq '.nodes[] | select(.host == strenv(HOST)) | .ip' topf.yaml)
    talosctl -n "$ip" get machineconfig v1alpha1 -o jsonpath='{.spec}' >"$work/$host.live"
    index "$work/$host.live" >"$work/$host.live.json"
    index "$work/$host.yaml" >"$work/$host.new.json"
    changes=$(jq -rn --slurpfile a "$work/$host.live.json" --slurpfile b "$work/$host.new.json" '
        $a[0] as $a | $b[0] as $b
        | ([$b | keys[]] - [$a | keys[]] | map("+" + .))
          + ([$a | keys[]] - [$b | keys[]] | map("-" + .))
          + ([$a | keys[]] | map(select($b[.] != null and $a[.] != $b[.])) | map("~" + .))
        | join(" ")')
    if [[ -z "$changes" ]]; then
        printf '  %-10s no changes\n' "$host"
        continue
    fi
    pending=1
    case $(reboot_mode "$host") in
        *"without a reboot"*) reboot="no reboot" ;;
        *reboot*) reboot="REBOOT" ;;
        *) reboot="reboot unknown, see full diff" ;;
    esac
    printf '  %-10s %-14s %s\n' "$host" "[$reboot]" "$changes"
done

if ((pending == 0)); then
    rm -f "$log"
    exit 0
fi
echo "Full diff: $log"

gum confirm "Apply to all nodes, one at a time?"
topf apply --confirm=false
