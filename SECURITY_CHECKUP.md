# ClawBot Security Checkup — 2026-03-20

## Summary

A full-codebase security review was conducted across all Python scripts, shell scripts,
and configuration files in this repository. Six issues were identified and fixed in this
commit. Two lower-priority findings are noted as follow-up recommendations.

---

## Findings Fixed in This Commit

### CRITICAL — Hardcoded Vault Unseal Key
**File:** `vault_unseal.sh:3`

The Vault unseal key was hardcoded as a plaintext string in a version-controlled shell
script. Anyone with read access to this repo (including past clones or CI logs) could
unseal the Vault and retrieve all stored secrets.

**Fix:** The unseal key is now read from the `UNSEAL_KEY` environment variable at runtime.
The script exits with an error if the variable is not set. The key should be stored outside
the repository (e.g., `sudo cat /etc/vault/unseal.key` on the host, referenced via
systemd `EnvironmentFile=`).

**Action required:** Rotate the exposed unseal key and re-seal/re-unseal Vault.

---

### CRITICAL — Hardcoded Live Telegram Bot Token
**File:** `agents/hatfield-cfo/cfo-agent/clawbot.py:29`

A live Telegram bot token was hardcoded directly in source code. Any person with repo
access (or who viewed a past commit) could impersonate the bot, read all incoming
messages, and send arbitrary messages to registered chat IDs.

**Fix:** `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` are now read from environment variables
(`os.environ["TELEGRAM_TOKEN"]`, `os.environ["TELEGRAM_CHAT_ID"]`). The script will
raise a `KeyError` at startup if these are missing, making misconfiguration obvious.

**Action required:** Revoke the exposed token in @BotFather and generate a new one.
Store the new token in Vault at `clawbot/secrets` and in the systemd `EnvironmentFile`.

---

### HIGH — Hardcoded User IDs in telegram_bot.py
**File:** `telegram_bot.py:549, 576, 623`

The authorised Telegram user ID was hardcoded as the integer literal `8647502718` in
three separate authorization checks. This creates a maintenance risk (hard to rotate)
and leaks PII into source code.

**Fix:** A single `ALLOWED_USER_ID` constant is now loaded from `TELEGRAM_CHAT_ID`
at startup. All three authorization checks reference this constant.

---

### HIGH — Unauthenticated Flask Proxy Endpoints
**File:** `graph_proxy.py`

Five endpoints (`/calendar`, `/email`, `/usage`, `/history`, `/tracy`) were accessible
to any host that could reach port 8001, with no authentication. The server bound to
`0.0.0.0`, meaning any machine on the local network (or beyond, depending on firewall
rules) could read Microsoft 365 email/calendar data and Anthropic API usage.

**Fix:** A `_require_auth()` helper was added. When `PROXY_API_KEY` is set in the
environment, every protected endpoint requires the caller to send:

```
Authorization: Bearer <PROXY_API_KEY>
```

Requests without a valid token receive `401 Unauthorized`. The `/health` endpoint
remains unauthenticated for monitoring purposes.

**Action required:** Set `PROXY_API_KEY` to a strong random value in Vault/`.env`
and update any dashboard clients to send the header.

---

### HIGH — Unrestricted CORS Policy
**File:** `graph_proxy.py:13`

`CORS(app)` with no `origins` restriction allowed any web origin to issue cross-site
requests to the proxy, enabling browser-based credential theft if a user visited a
malicious page while the proxy was reachable.

**Fix:** CORS is now restricted to a configurable origin via `PROXY_ALLOWED_ORIGIN`
(defaults to `http://localhost:3000`). Set this env var to match the actual dashboard
URL in production.

---

### MEDIUM — Exception Details Exposed to Telegram Users
**File:** `telegram_bot.py:542`

Raw Python exception strings were sent back to the Telegram user:
```python
await update.message.reply_text("Error: " + str(e))
```
This could leak internal file paths, database errors, API responses, or stack traces.

**Fix:** The user now receives the generic message "Sorry, something went wrong. Please
try again." The full exception is still written to the audit log.

---

## Remaining Recommendations (Not Auto-Fixed)

### MEDIUM — Vault Communicates Over HTTP
**Files:** `vault_secrets.py:6`, `vault_unseal.sh:2`

`VAULT_ADDR = "http://127.0.0.1:8200"` uses plain HTTP even for localhost. While
loopback reduces external exposure, a TLS listener is still best practice and prevents
certain local attack vectors (e.g., abstract Unix sockets, container networking).

**Recommendation:** Enable TLS on the Vault listener and update `VAULT_ADDR` to `https://`.

---

### LOW — `permission_mode="bypassPermissions"` in Agent SDK
**Files:** `agents/hatfield-cfo/cfo-agent/clawbot.py:77,98`, `agents/hatfield-cfo/cfo-agent/agent.py:320`

Both the Hatfield orchestrator and Mr Soul CFO agent run with `bypassPermissions` and
have `"Bash"` in their `allowed_tools` list. This means a prompt-injection attack (e.g.,
malicious content in a financial document or email) could cause the agent to execute
arbitrary shell commands on the host without any confirmation prompt.

**Recommendation:** Use `permission_mode="default"` and remove `"Bash"` from
`allowed_tools` unless the specific use case requires shell execution. If shell access
is genuinely needed, consider sandboxing (e.g., Docker, restricted user, seccomp).

---

## New Environment Variables Required

| Variable | Used In | Purpose |
|---|---|---|
| `UNSEAL_KEY` | `vault_unseal.sh` | Vault unseal key (previously hardcoded) |
| `TELEGRAM_TOKEN` | `agents/hatfield-cfo/cfo-agent/clawbot.py` | Bot token (previously hardcoded) |
| `TELEGRAM_CHAT_ID` | `clawbot.py`, `telegram_bot.py` | Allowed chat/user ID (previously hardcoded) |
| `PROXY_API_KEY` | `graph_proxy.py` | Bearer token for proxy endpoints |
| `PROXY_ALLOWED_ORIGIN` | `graph_proxy.py` | CORS allowed origin (default: `http://localhost:3000`) |

All of these should be stored in HashiCorp Vault under `clawbot/secrets` and referenced
via the existing `vault_secrets.py` loader.
