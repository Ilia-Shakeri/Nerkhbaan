#!/bin/sh

set -u

PRIMARY_REGISTRY="${NPM_REGISTRY_PRIMARY:-https://package-mirror.liara.ir/repository/npm/}"
SECONDARY_REGISTRY="${NPM_REGISTRY_SECONDARY:-https://mirror2.chabokan.net/npm/}"
FALLBACK_REGISTRY="${NPM_REGISTRY_FALLBACK:-https://registry.npmjs.org/}"

show_config() {
    echo "Registry: $(npm config get registry)"
    echo "fetch-timeout: $(npm config get fetch-timeout)"
    echo "fetch-retries: $(npm config get fetch-retries)"
    echo "maxsockets: $(npm config get maxsockets)"
    echo "omit-lockfile-registry-resolved: $(npm config get omit-lockfile-registry-resolved)"
}

registry_is_reachable() {
    registry="$1"
    NPM_CONFIG_FETCH_TIMEOUT=10000 \
    NPM_CONFIG_FETCH_RETRIES=0 \
    npm ping --registry="$registry" --loglevel=error >/dev/null 2>&1
}

install_from_registry() {
    registry="$1"
    if ! npm config set registry "$registry" --location=project; then
        echo "Could not set npm registry: $registry" >&2
        return 1
    fi

    echo "Using:"
    echo "$registry"
    show_config
    echo
    echo "Installing dependencies..."

    npm ci \
        --workspace=nerkhbaan-web \
        --workspace=@nerkhbaan/ui \
        --include-workspace-root=false \
        --registry="$registry" \
        --no-audit \
        --no-fund
}

echo "Checking npm mirrors..."

for registry in "$PRIMARY_REGISTRY" "$SECONDARY_REGISTRY" "$FALLBACK_REGISTRY"; do
    if registry_is_reachable "$registry"; then
        echo "OK $registry"
        if install_from_registry "$registry"; then
            echo "Dependency install complete."
            exit 0
        else
            status=$?
        fi

        echo "Install failed with registry: $registry" >&2
        echo "npm exit code: $status" >&2
        show_config >&2
    else
        echo "FAIL $registry" >&2
    fi
done

echo "All npm registries failed. No dependency set was installed." >&2
exit 1
