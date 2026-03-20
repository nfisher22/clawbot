#!/bin/bash
export VAULT_ADDR='https://127.0.0.1:8200'

# UNSEAL_KEY must be set in the environment or loaded from a secured file outside this repo.
# Never hardcode unseal keys in source files.
# Example: export UNSEAL_KEY=$(cat /etc/vault/unseal.key)
if [ -z "$UNSEAL_KEY" ]; then
    echo "ERROR: UNSEAL_KEY environment variable is not set." >&2
    echo "Set it before calling this script, e.g.:" >&2
    echo "  export UNSEAL_KEY=\$(cat /etc/vault/unseal.key)" >&2
    exit 1
fi

# Wait for Vault to start
sleep 5

# Check if sealed
SEALED=$(vault status 2>/dev/null | grep "Sealed" | awk '{print $2}')
if [ "$SEALED" = "true" ]; then
    echo "Vault is sealed — unsealing..."
    vault operator unseal "$UNSEAL_KEY"
    echo "Vault unsealed at $(date)"
else
    echo "Vault already unsealed"
fi
