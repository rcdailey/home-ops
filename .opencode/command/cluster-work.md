---
description: Establish collaborative GitOps workflow and investigate cluster state
---

# Cluster Work Protocol

**MISSION**: Check Kubernetes events first at each investigation cycle, then systematically
investigate cluster state using read-only operations to identify issues and propose GitOps-based
solutions.

**SCOPE**: $ARGUMENTS

*If no arguments provided, infer investigation scope from recent conversation context.*

## Investigation Priority

1. **Events First** - Always use `mcp__k8s__kubectl_get` for events (allNamespaces=true,
   sortBy=lastTimestamp, headLimit=50)
2. **Follow the Pipeline** - Kustomization → HelmRelease → Pod → Container logs
3. **Research When Stuck** - Use web search to verify approaches, find latest docs, break assumption
   cycles
4. **Context Focus** - Current session task, but follow issues where they lead
5. **Collaborative** - Present findings, ask questions, propose solutions

## What I Will Do

**Immediate Actions:**

- Check recent Kubernetes events across ALL namespaces using `mcp__k8s__kubectl_get`
- Assess Flux reconciliation status
- Identify pod/container issues
- Compare cluster state to GitOps configuration

**Collaboration Mode:**

- Present findings with evidence
- Ask clarifying questions when multiple solutions exist
- Explain tradeoffs of different approaches
- Wait for your approval before making changes

**When Struggling:**

- Stop and step back to question current approach
- Web search for accurate information and latest documentation
- Cross-reference findings to avoid assumption-based cycles
- Verify understanding before continuing

**GitOps Changes Only:**

- Modify YAML files in this repository
- Run `pre-commit run --files <changed-files>`
- Stop and wait for you to commit/push
- Never modify cluster directly

## Investigation Flow

```yaml
1. Events: Recent warnings/errors across namespaces
2. Flux: GitRepository, Kustomization, HelmRelease status
3. Resources: Pods, Services, ConfigMaps, Secrets, PVCs
4. Logs: Application and system container logs
5. Network: HTTPRoutes, Services, Endpoints
6. Dependencies: Databases, external services
```

## Read-Only Operations

**Primary (MCP k8s tools):**

- `mcp__k8s__kubectl_get` - Events across all namespaces (most recent first, limit 50, expand if
  needed)
- `mcp__k8s__kubectl_describe` - Detailed resource information
- `mcp__k8s__kubectl_logs` - Application and container logs
- `mcp__k8s__exec_in_pod` - Execute diagnostic commands in pods

**Secondary (bash commands):**

- Flux status and reconciliation commands
- GitOps file analysis and validation

**PROHIBITED**: apply, delete, patch, edit, scale, or any cluster mutations

## Communication Style

**Default**: Focused and actionable

- Lead with event findings
- Highlight issues with evidence
- Present solutions with reasoning
- Ask questions when direction needed

**When Complex**: Educational explanations for learning opportunities

## Session Agreement

This command establishes our collaborative workflow:

1. **Investigation** → I check cluster state starting with events
2. **Analysis** → I identify root causes and propose solutions
3. **Discussion** → We discuss options and agree on approach
4. **Implementation** → I modify GitOps YAML files only
5. **Validation** → I run pre-commit checks
6. **Handoff** → You commit/push changes
7. **Next Cycle** → Return to step 1 to verify resolution or identify new issues

## Critical Reminders

- **EVENTS FIRST** - Use `mcp__k8s__kubectl_get` for events (allNamespaces=true,
  sortBy=lastTimestamp, headLimit=50)
- **RESEARCH OVER ASSUMPTIONS** - Web search when uncertain, verify approaches, break guess cycles
- **COLLABORATIVE** - No unilateral decisions, always discuss
- **GITOPS ONLY** - Never modify cluster, only repository YAML
- **VALIDATE** - Always run pre-commit before handoff
- **REFERENCE** - Use `file.yaml:123` when citing code
- **SCOPE** - Focus on session task but remain open to root causes
