#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)

if [ -f $REPO_ROOT/.env ]; then
  echo "Loading .env file"
  set -o allexport
  # shellcheck disable=SC1091
  source .env
  set +o allexport
fi

# ----------------------------------
# Required environment variables
# ----------------------------------
# Make sure these are exported in your shell or defined in .env
# If SIGNER_KEY_PATH is not set in the environment or .env, use this default:
SIGNER_KEY_PATH="${SIGNER_KEY_PATH:-$REPO_ROOT/ethereum_private_key.txt}"
: "${DERIVE_SC_WALLET_ADDRESS:?Environment variable DERIVE_SC_WALLET_ADDRESS must be set (or in .env)}"
: "${SIGNER_KEY_PATH:?Environment variable SIGNER_KEY_PATH must be set (or in .env)}"

if [ ! -f "$SIGNER_KEY_PATH" ]; then
  echo "Error: signer key not found at $SIGNER_KEY_PATH" >&2
  exit 1
fi


# -----------------------------
# Constants
# -----------------------------
CHAINS=(BASE OPTIMISM ARBITRUM)
CURRENCIES=(USDC OLAS DRV)
MODES=(withdraw deposit)

# -----------------------------
# Helper for running a single test
# -----------------------------
failures=()

run_test() {
  local chain=$1
  local currency=$2
  local mode=$3

  # we withdraw first, then deposit only 10% of that to account for protocol fees (and gas cost for DRV)
  local key="${currency}_${mode}"
  case "$key" in
    USDC_withdraw) amount=1 ;;
    USDC_deposit ) amount=0.1 ;;
    OLAS_withdraw) amount=4 ;;
    OLAS_deposit ) amount=0.4 ;;
    DRV_withdraw ) amount=10 ;;
    DRV_deposit  ) amount=1 ;;
  esac

  echo "→ Testing: $mode on $chain for $currency"
  drv --derive-sc-wallet "$DERIVE_SC_WALLET_ADDRESS" \
      --signer-key-path "$SIGNER_KEY_PATH" \
      bridge "$mode" \
      -c "$chain" \
      -t "$currency" \
      -a "$amount"
  rc=$?
  if [ $rc -ne 0 ]; then
    failures+=("$mode|$chain|$currency|exit_code=$rc")
    echo "✖ Failed: $mode on $chain for $currency (exit $rc)"
  else
    echo "✔ Success: $mode on $chain for $currency"
  fi
  echo
}

# -----------------------------
# Main loop
# -----------------------------
for chain in "${CHAINS[@]}"; do
  for currency in "${CURRENCIES[@]}"; do
    for mode in "${MODES[@]}"; do
      run_test "$chain" "$currency" "$mode"
    done
  done
done

# -----------------------------
# Summary & Exit
# -----------------------------
if [ ${#failures[@]} -gt 0 ]; then
  echo "=== TEST SUMMARY ==="
  echo "Some tests failed:"
  for f in "${failures[@]}"; do
    echo "  • $f"
  done
  exit 1
else
  echo "=== TEST SUMMARY ==="
  echo "All tests passed successfully!"
  exit 0
fi
