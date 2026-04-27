#!/usr/bin/env bash
# Build aarch64-targeted Python dependency bundles for AgentCore Runtime.
#
# AgentCore Runtime enforces a 30-second init limit. Pre-building deps
# into zip bundles eliminates the pip install phase during cold start.
#
# Produces two bundles in backend/agentcore-deps/:
#   base.zip       — bedrock-agentcore + boto3 (Templates 1, 2, default)
#   strands-mcp.zip — bedrock-agentcore + boto3 + strands-agents + strands-agents-tools + mcp (Template 3, tools)
#
# Both bundles include boto3/botocore (NOT pre-installed in AgentCore Runtime)
# and strip __pycache__ directories and .pyc files.
#
# Usage:
#   ./scripts/install-agentcore-deps.sh
#
# This is called automatically by scripts/deploy.sh before CDK deploy.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUTPUT_DIR="${PROJECT_ROOT}/backend/agentcore-deps"

PIP_PLATFORM_FLAGS=(
  --platform manylinux2014_aarch64
  --python-version 3.13
  --implementation cp
  --only-binary=:all:
)

# ── Helper functions ──────────────────────────────────────────────────

log_info() {
  echo -e "\033[1;34m[INFO]\033[0m $*"
}

log_success() {
  echo -e "\033[1;32m[SUCCESS]\033[0m $*"
}

log_error() {
  echo -e "\033[1;31m[ERROR]\033[0m $*" >&2
}

# Install packages into a target directory.
install_packages() {
  local target_dir="$1"
  shift
  local packages=("$@")

  mkdir -p "${target_dir}"

  pip3 install \
    "${PIP_PLATFORM_FLAGS[@]}" \
    --target "${target_dir}" \
    --quiet \
    "${packages[@]}"

  remove_cache_files "${target_dir}"
}

# Remove __pycache__ directories and .pyc files.
remove_cache_files() {
  local target_dir="$1"

  find "${target_dir}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
  find "${target_dir}" -type f -name "*.pyc" -delete 2>/dev/null || true
}

# Create a zip from a directory's contents and remove the directory.
create_bundle_zip() {
  local target_dir="$1"
  local zip_path="$2"

  (cd "${target_dir}" && zip -r -q "${zip_path}" .)
  rm -rf "${target_dir}"
}

# ── Main ──────────────────────────────────────────────────────────────

main() {
  log_info "Installing AgentCore deps into backend/agentcore-deps/ (targeting aarch64)"

  # Idempotent: clean and rebuild output directory each run
  rm -rf "${OUTPUT_DIR}"
  mkdir -p "${OUTPUT_DIR}"

  # Bundle 1: base (bedrock-agentcore + boto3)
  log_info "Building base bundle (bedrock-agentcore + boto3)..."
  local base_dir="${OUTPUT_DIR}/base"
  install_packages "${base_dir}" bedrock-agentcore boto3
  create_bundle_zip "${base_dir}" "${OUTPUT_DIR}/base.zip"

  # Bundle 2: strands-mcp (bedrock-agentcore + boto3 + strands-agents + strands-agents-tools + mcp)
  log_info "Building strands-mcp bundle (bedrock-agentcore + boto3 + strands-agents + strands-agents-tools + mcp)..."
  local strands_dir="${OUTPUT_DIR}/strands-mcp"
  install_packages "${strands_dir}" bedrock-agentcore boto3 strands-agents strands-agents-tools mcp
  create_bundle_zip "${strands_dir}" "${OUTPUT_DIR}/strands-mcp.zip"

  local base_size strands_size
  base_size=$(du -sh "${OUTPUT_DIR}/base.zip" | cut -f1)
  strands_size=$(du -sh "${OUTPUT_DIR}/strands-mcp.zip" | cut -f1)

  log_success "Bundles created: base.zip (${base_size}), strands-mcp.zip (${strands_size})"
}

main "$@"
