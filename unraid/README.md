# home-ops files on Unraid

Installed from <https://github.com/rcdailey/home-ops> (unraid/ directory).

nfs-drain asks the Kubernetes cluster to scale NFS apps to zero before the array stops. It runs from
/boot/config/stop and from an emhttp "stopping" hook that /boot/config/go installs. Files, install,
test, and removal: docs/runbooks/unraid-nfs-drain.md in that repository.

unraid-state (unraid-state.sh in Git) writes Unraid array and disk state for node_exporter
(my-node-exporter.xml). /boot/config/go starts it at boot. Details:
docs/runbooks/unraid-telemetry.md.
