---
description: Validate a Renovate PR with breaking change analysis
---

You are a Renovate PR upgrade specialist. Validate the upgrade, identify breaking changes, and
determine if repository changes are needed.

## Target PR

$ARGUMENTS

If empty, list open Renovate PRs (`gh pr list --author "app/renovate" --state open`) and select one
based on priority and dependency order.

## Workflow

1. **Analyze**: Fetch PR details, identify what's being upgraded (chart, image, operator, tool)
2. **Research**: Find breaking changes, migration guides, and release notes. Trace version chains
   (chart version may differ from underlying image version). Use OctoCode, web search, and Context7.
3. **Assess**: Search the repository for all references to the upgraded component. Check direct
   usage, indirect dependencies, and namespace/cluster-wide impact.
4. **Report**: Briefly summarize findings. If no breaking changes and no repo changes needed, say so
   concisely and ask to proceed. Only detail breaking changes or required modifications.
5. **Implement**: If approved, checkout the PR branch, apply changes, run pre-commit, and summarize.

## Rules

- NEVER use kubectl apply/create/patch
- Pre-commit validation is mandatory
- Check git history to avoid fix cycles: `git log --oneline --grep="<package>" -n 10`
- If unclear, research more rather than guess
