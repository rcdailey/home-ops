set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

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
