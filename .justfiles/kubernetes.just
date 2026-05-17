set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

root := justfile_directory()

[private]
default:
    @just --list kubernetes

# Interactive node selection helper
[private]
select-node prompt="Select node":
    @kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | fzf --prompt="{{prompt}}: "

[doc('List Kubernetes nodes with status')]
list-nodes:
    kubectl get nodes -o wide

[doc('Add out-of-service taint to a dead node (enables CSI fencing)')]
fence-node node="":
    #!/usr/bin/env bash
    set -euo pipefail
    node="{{node}}"
    if [ -z "$node" ]; then
        node=$(just kubernetes select-node "Select node to fence")
    fi
    kubectl taint node "$node" node.kubernetes.io/out-of-service=nodeshutdown:NoExecute --overwrite

[confirm("Only remove this taint AFTER the node has completed a full power cycle! Continue?")]
[doc('Remove out-of-service taint from a node')]
unfence-node node="":
    #!/usr/bin/env bash
    set -euo pipefail
    node="{{node}}"
    if [ -z "$node" ]; then
        node=$(just kubernetes select-node "Select node to unfence")
    fi
    kubectl taint node "$node" node.kubernetes.io/out-of-service=nodeshutdown:NoExecute-

[doc('Show nodes with out-of-service taint')]
show-fenced-nodes:
    @kubectl get nodes -o jsonpath='{range .items[?(@.spec.taints)]}{.metadata.name}{"\t"}{range .spec.taints[*]}{.key}={.value}:{.effect}{" "}{end}{"\n"}{end}' | rg out-of-service || echo "No fenced nodes"

[doc('Enable fencing on ceph-csi RBD driver')]
enable-fencing:
    kubectl patch drivers.csi.ceph.io -n rook-ceph rook-ceph.rbd.csi.ceph.com --type merge -p '{"spec":{"enableFencing":true}}'

[doc('Disable fencing on ceph-csi RBD driver')]
disable-fencing:
    kubectl patch drivers.csi.ceph.io -n rook-ceph rook-ceph.rbd.csi.ceph.com --type merge -p '{"spec":{"enableFencing":false}}'

[doc('Show current fencing configuration')]
show-fencing-status:
    @kubectl get drivers.csi.ceph.io -n rook-ceph -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}enableFencing={.spec.enableFencing}{"\n"}{end}'

[doc('Show Ceph cluster health, PGs, OSDs, and capacity')]
ceph-status:
    cd "{{root}}" && ./scripts/hops.py storage ceph status

[doc('Open a debug shell on a node')]
node-shell node="":
    #!/usr/bin/env bash
    set -euo pipefail
    node="{{node}}"
    if [ -z "$node" ]; then
        node=$(just kubernetes select-node "Select node")
    fi
    kubectl debug node/"$node" -n default -it --image=alpine:latest --profile sysadmin

[doc('Delete pods in Failed, Pending, or Succeeded state')]
prune-pods:
    #!/usr/bin/env bash
    for phase in Failed Pending Succeeded; do
        kubectl delete pods -A --field-selector status.phase="$phase" --ignore-not-found=true
    done

[confirm("This will force delete all Terminating pods on the selected node. Continue?")]
[doc('Force delete pods stuck in Terminating state on a node')]
force-delete-terminating node="":
    #!/usr/bin/env bash
    set -euo pipefail
    node="{{node}}"
    if [ -z "$node" ]; then
        node=$(just kubernetes select-node "Select node")
    fi
    kubectl get pods -A --field-selector spec.nodeName="$node" -o json | \
        jq -r '.items[] | select(.metadata.deletionTimestamp != null) | "\(.metadata.namespace) \(.metadata.name)"' | \
        xargs -r -n2 sh -c 'kubectl delete pod -n $0 $1 --force --grace-period=0'

[confirm("This will delete all VolumeAttachments for the selected node. Continue?")]
[doc('Delete stale VolumeAttachments for a dead node')]
delete-stale-attachments node="":
    #!/usr/bin/env bash
    set -euo pipefail
    node="{{node}}"
    if [ -z "$node" ]; then
        node=$(just kubernetes select-node "Select node")
    fi
    kubectl get volumeattachments -o json | \
        jq -r ".items[] | select(.spec.nodeName==\"$node\") | .metadata.name" | \
        xargs -r -I {} kubectl delete volumeattachment {} --force --grace-period=0

[doc('Authenticate claude-proxy with Anthropic OAuth')]
claude-proxy-login:
    #!/usr/bin/env bash
    set -euo pipefail

    # Get the management password from the running secret
    MGMT_KEY=$(kubectl get secret -n default claude-proxy-secret -o jsonpath='{.data.MANAGEMENT_PASSWORD}' | base64 -d)

    # Find the claude-proxy pod
    POD=$(kubectl get pod -n default -l app.kubernetes.io/name=claude-proxy -o jsonpath='{.items[0].metadata.name}')
    if [ -z "$POD" ]; then
        echo "Error: claude-proxy pod not found"
        exit 1
    fi

    # Port-forward API (8317) and OAuth callback (54545)
    kubectl port-forward -n default "$POD" 8317:8317 54545:54545 >/dev/null 2>&1 &
    PF_PID=$!
    trap "kill $PF_PID 2>/dev/null" EXIT
    sleep 2

    # Initiate OAuth flow via management API
    RESPONSE=$(curl -sf -H "Authorization: Bearer $MGMT_KEY" \
        "http://localhost:8317/v0/management/anthropic-auth-url?is_webui=true")
    AUTH_URL=$(echo "$RESPONSE" | jq -r '.url')
    STATE=$(echo "$RESPONSE" | jq -r '.state')

    if [ -z "$AUTH_URL" ] || [ "$AUTH_URL" = "null" ]; then
        echo "Error: failed to get auth URL from management API"
        echo "$RESPONSE"
        exit 1
    fi

    echo "Opening Anthropic login in your browser..."
    open "$AUTH_URL"

    # Poll get-auth-status: returns {"status":"wait"} while pending,
    # {"status":"ok"} on success, {"status":"error","error":"..."} on failure
    echo "Waiting for OAuth callback..."
    for i in $(seq 1 60); do
        sleep 2
        STATUS=$(curl -sf -H "Authorization: Bearer $MGMT_KEY" \
            "http://localhost:8317/v0/management/get-auth-status?state=$STATE" || true)
        RESULT=$(echo "$STATUS" | jq -r '.status' 2>/dev/null || true)
        if [ "$RESULT" = "ok" ]; then
            echo "Authentication successful!"
            exit 0
        fi
        if [ "$RESULT" = "error" ]; then
            echo "Error: $(echo "$STATUS" | jq -r '.error')"
            exit 1
        fi
    done

    echo "Timed out waiting for OAuth callback (120s)"
    exit 1
