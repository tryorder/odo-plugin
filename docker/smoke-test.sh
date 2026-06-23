#!/usr/bin/env bash
# Smoke-test the Order Connector plugin endpoints.
#
#   ./smoke-test.sh <API_KEY> [BASE_URL]
#
# Example:
#   ./smoke-test.sh my-secret-key http://localhost:8069
set -euo pipefail

API_KEY="${1:?Usage: ./smoke-test.sh <API_KEY> [BASE_URL]}"
BASE_URL="${2:-http://localhost:8069}"
H=(-H "X-Api-Key: ${API_KEY}" -H "Content-Type: application/json")

echo "== 1) ping =="
curl -fsS "${H[@]}" "${BASE_URL}/order_connector/ping" | python3 -m json.tool

echo; echo "== 2) branches =="
curl -fsS "${H[@]}" "${BASE_URL}/order_connector/branches" | python3 -m json.tool

echo; echo "== 3) catalog (first 1200 chars) =="
curl -fsS "${H[@]}" "${BASE_URL}/order_connector/catalog" | head -c 1200; echo

echo; echo "== 4) create order (uses product_id from catalog) =="
echo "   Edit PRODUCT_ID below to a real product.template id from the catalog, then re-run:"
PRODUCT_ID="${PRODUCT_ID:-}"
if [[ -n "${PRODUCT_ID}" ]]; then
  curl -fsS -X POST "${H[@]}" "${BASE_URL}/order_connector/orders" -d "{
    \"order\": {
      \"provider_order_id\": \"SMOKE-001\",
      \"order_type\": \"pickup\",
      \"customer\": {\"name\": \"Smoke Test\", \"phone\": \"0500000000\"},
      \"items\": [{\"product_id\": \"${PRODUCT_ID}\", \"qty\": 1, \"price\": 10.0}]
    }
  }" | python3 -m json.tool
else
  echo "   (skipped: set PRODUCT_ID=<id> to test order creation)"
fi

echo; echo "✓ smoke test done"
