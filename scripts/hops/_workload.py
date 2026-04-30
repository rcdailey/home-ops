"""Shared workload resolution across app and query domains.

Resolves user-provided app names to concrete workloads using multiple
matching strategies, ordered by specificity:

1. Exact: workload name == input
2. Label: pod template app.kubernetes.io/name (or app) label == input
3. Suffix: workload name ends with -{input} (subchart naming convention)
4. Prefix: workload name starts with {input}- (partial name shorthand)
5. Substring: input appears anywhere in workload name (hyphen-insensitive)
"""

from __future__ import annotations

from hops._runner import kubectl_json

WORKLOAD_KINDS = ("deployments", "statefulsets", "daemonsets", "cronjobs", "jobs")

# Short labels for table output
KIND_LABELS = {
    "deployments": "D",
    "statefulsets": "S",
    "daemonsets": "DS",
    "cronjobs": "CJ",
    "jobs": "J",
}


class Workload:
    """Resolved workload with metadata needed by callers."""

    __slots__ = ("namespace", "name", "kind", "raw")

    def __init__(self, namespace: str, name: str, kind: str, raw: dict):
        self.namespace = namespace
        self.name = name
        self.kind = kind
        self.raw = raw

    def pod_template(self) -> dict:
        """Extract the pod template spec from the workload."""
        spec = self.raw.get("spec", {})
        if self.kind == "cronjobs":
            spec = spec.get("jobTemplate", {}).get("spec", {})
        return spec.get("template", {})

    def pod_labels(self) -> dict:
        """Labels from the pod template metadata."""
        return self.pod_template().get("metadata", {}).get("labels", {})

    def pod_spec(self) -> dict:
        """The pod spec from the template."""
        return self.pod_template().get("spec", {})

    def app_label(self) -> str:
        """The effective app name from pod labels."""
        labels = self.pod_labels()
        return labels.get("app.kubernetes.io/name", labels.get("app", ""))


def find_workloads(
    name: str,
    namespace: str | None = None,
) -> list[Workload]:
    """Find workloads matching name with cascading match strategies.

    Returns only the highest-priority tier that has matches (exact > label
    > suffix > prefix). Within a tier, results are sorted by namespace
    then name.
    """
    exact: list[Workload] = []
    by_label: list[Workload] = []
    suffix: list[Workload] = []
    prefix: list[Workload] = []
    substring: list[Workload] = []
    name_norm = name.lower().replace("-", "")

    for kind in WORKLOAD_KINDS:
        data = kubectl_json(kind, namespace=namespace)
        for item in data.get("items", []):
            meta = item.get("metadata", {})
            wl_name = meta.get("name", "")
            wl_ns = meta.get("namespace", "")
            wl = Workload(wl_ns, wl_name, kind, item)

            if wl_name == name:
                exact.append(wl)
            else:
                if wl.app_label() == name:
                    by_label.append(wl)
                if wl_name.endswith(f"-{name}"):
                    suffix.append(wl)
                if wl_name.startswith(f"{name}-"):
                    prefix.append(wl)
                wl_norm = wl_name.lower().replace("-", "")
                if name_norm in wl_norm and wl not in prefix and wl not in suffix:
                    substring.append(wl)

    result = exact or by_label or suffix or prefix or substring
    result.sort(key=lambda w: (w.namespace, w.name))
    return result


def all_workload_names(namespace: str | None = None) -> list[str]:
    """Return all workload names (for near-match suggestions)."""
    names: list[str] = []
    for kind in WORKLOAD_KINDS:
        data = kubectl_json(kind, namespace=namespace)
        for item in data.get("items", []):
            names.append(item.get("metadata", {}).get("name", ""))
    return sorted(set(names))


def suggest_near_matches(name: str, namespace: str | None = None) -> list[str]:
    """Find workload names similar to input (substring, hyphen-insensitive)."""
    candidates = all_workload_names(namespace)
    # Normalize by stripping hyphens for comparison so "victoriametrics"
    # matches "victoria-metrics-k8s-stack"
    norm = name.lower().replace("-", "")
    hits: list[str] = []
    for c in candidates:
        if c == name:
            continue
        c_norm = c.lower().replace("-", "")
        if norm in c_norm or c_norm.startswith(norm):
            hits.append(c)
        if len(hits) >= 5:
            break
    return hits


def resolve_app(
    name: str,
    namespace: str | None = None,
) -> Workload | None:
    """Resolve an app name to a single workload (first match)."""
    matches = find_workloads(name, namespace)
    return matches[0] if matches else None
