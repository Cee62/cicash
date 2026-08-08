#!/usr/bin/env bash
# From nothing to an agent with a bounded budget, in four commands.
set -euo pipefail
cd "$(dirname "$0")/.."

DB=${DB:-./ac.db}
W=${W:-./wallet.json}

# 1. the principal issues a bounded grant  (human types this)
python3 -m cicash.cli --db "$DB" grant \
  --budget 50 --per-tx 5 --rate-count 20 --rate-window 60 --ttl-h 24 \
  --payees api.search,api.gpu --purposes research \
  --merchants api.search,api.gpu \
  --note "research agent" --out "$W"

# 2. what did we actually hand over?
python3 -m cicash.cli --db "$DB" balance --wallet "$W"

# 3. point any MCP client at it (see examples/mcp_config.json)
echo
echo "MCP:  CICASH_DB=$DB CICASH_WALLET=$W python3 -m cicash.mcp_server"
echo "HTTP: python3 -m cicash.cli --db $DB serve"
echo

# 4. the kill switch, whenever you want it
echo "revoke with:  python3 -m cicash.cli --db $DB revoke --wallet $W"
