# yaml-language-server: $schema=https://raw.githubusercontent.com/siderolabs/talos/refs/heads/main/pkg/machinery/config/schemas/config.schema.json
---
cluster:
  etcd:
    extraArgs:
      listen-metrics-urls: http://0.0.0.0:2381
      auto-compaction-mode: periodic
      auto-compaction-retention: 24h
    advertisedSubnets:
      - 192.168.1.0/24
---
apiVersion: v1alpha1
kind: KubeNodeConfig
labels:
  node-role.kubernetes.io/control-plane: ""
  node.kubernetes.io/exclude-from-external-load-balancers: ""
# Control-plane nodes also run workloads.
taints:
  node-role.kubernetes.io/control-plane:
    $patch: delete
---
apiVersion: v1alpha1
kind: KubeAdmissionControlConfig
name: PodSecurity
configuration:
  apiVersion: pod-security.admission.config.k8s.io/v1alpha1
  kind: PodSecurityConfiguration
  defaults:
    audit: restricted
    audit-version: latest
    enforce: baseline
    enforce-version: latest
    warn: restricted
    warn-version: latest
  # Lists append to the generated defaults, which already exempt the kube-system namespace.
  exemptions:
    runtimeClasses:
      # Workload allowlist: kubernetes/apps/kube-system/pod-security
      - psa-exempt
    usernames: []
---
apiVersion: v1alpha1
kind: KubeAuditPolicyConfig
configuration:
  apiVersion: audit.k8s.io/v1
  kind: Policy
  omitStages:
    - RequestReceived
  rules:
    # Controllers create pods as service accounts; keep these so Pod Security denials name the pod.
    - level: Metadata
      verbs:
        - create
      resources:
        - group: ""
          resources:
            - pods
    - level: None
      userGroups:
        - system:serviceaccounts
    - level: Metadata
---
apiVersion: v1alpha1
kind: KubeAuthenticationConfig
configuration:
  anonymous:
    conditions:
      - path: /livez
      - path: /readyz
      - path: /healthz
    enabled: true
  jwt:
    - issuer:
        url: https://auth.{{ env "SECRET_DOMAIN" }}
        audiences:
          - headlamp
      claimMappings:
        username:
          claim: email
          prefix: ""
        groups:
          claim: groups
          prefix: "oidc:"
      userValidationRules:
        - expression: "!user.username.startsWith('system:')"
          message: username cannot use the reserved system prefix
---
apiVersion: v1alpha1
kind: KubeAuthorizerConfig
name: node
type: Node
---
apiVersion: v1alpha1
kind: KubeAuthorizerConfig
name: rbac
type: RBAC
---
apiVersion: v1alpha1
kind: KubeServiceAccountConfig
issuer:
  issuerURL: https://192.168.1.70:6443
---
apiVersion: v1alpha1
kind: KubeAPIServerConfig
certExtraSANs:
  - 127.0.0.1
  - 192.168.1.70
extraArgs:
  enable-aggregator-routing: "true"
  feature-gates: HPAScaleToZero=true,MutatingAdmissionPolicy=true
  runtime-config: admissionregistration.k8s.io/v1beta1=true
---
apiVersion: v1alpha1
kind: KubeControllerManagerConfig
extraArgs:
  bind-address: 0.0.0.0
  feature-gates: HPAScaleToZero=true
  terminated-pod-gc-threshold: "100"
---
apiVersion: v1alpha1
kind: KubeSchedulerConfig
extraArgs:
  bind-address: 0.0.0.0
config:
  profiles:
    - schedulerName: default-scheduler
      plugins:
        score:
          disabled:
            - name: ImageLocality
      pluginConfig:
        - name: PodTopologySpread
          args:
            defaultingType: List
            defaultConstraints:
              - maxSkew: 1
                topologyKey: kubernetes.io/hostname
                whenUnsatisfiable: ScheduleAnyway
---
apiVersion: v1alpha1
kind: KubeTalosAPIAccessConfig
allowedRoles:
  - os:admin
allowedKubernetesNamespaces:
  - system-upgrade
---
apiVersion: v1alpha1
kind: KubeProxyConfig
enabled: false
---
apiVersion: v1alpha1
kind: KubeCoreDNSConfig
enabled: false
