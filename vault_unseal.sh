#!/bin/bash
export VAULT_ADDR='http://127.0.0.1:8200'
UNSEAL_KEY="cJgG3SOuFmyjye+HYL1wy9j9KHa+mzIBqj1HIA7gWX0="

# Wait for Vault to start
sleep 5

# Check if sealed
SEALED=$(vault status 2>/dev/null | grep "Sealed" | awk '{print $2}')
if [ "$SEALED" = "true" ]; then
    echo "Vault is sealed — unsealing..."
    vault operator unseal $UNSEAL_KEY
    echo "Vault unsealed at $(date)"
else
    echo "Vault already unsealed"
fi
