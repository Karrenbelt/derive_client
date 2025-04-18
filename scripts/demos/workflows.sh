#!/usr/bin/env bash
set -eu pipefail

source scripts/demos/base.sh

call_and_wait "bash demo.sh" 3
