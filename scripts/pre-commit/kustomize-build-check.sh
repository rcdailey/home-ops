#!/bin/bash

# Source dependency checker
source "$(dirname "$0")/check-dependencies.sh"

# Check if kustomize is available
if ! check_dependency "kustomize" "brew install kustomize"; then
    exit 1
fi

# Run kustomize build validation
echo "🔨 Running kustomize build validation..."
failed=0

for dir in $(find kubernetes/apps -name kustomization.yaml -printf "%h\n"); do
    if (cd "$dir" && kustomize build . >/dev/null 2>&1); then
        echo "✅ $dir"
    else
        echo "❌ $dir - kustomize build failed"
        failed=1
    fi
done

if [[ $failed -eq 1 ]]; then
    echo "💡 Run 'kustomize build' in the failing directories for details"
    exit 1
fi

echo "🎉 All kustomizations build successfully"
