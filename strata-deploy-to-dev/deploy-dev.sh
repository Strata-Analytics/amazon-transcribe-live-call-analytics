#!/bin/bash
# =============================================================================
# deploy-dev.sh — Packaging + deploy del stack agent-copilot-dev
#
# Uso:
#   ./strata-deploy-to-dev/deploy-dev.sh
#
# Lo que hace:
#   1. Corre publish.sh (packagéa solo los sub-stacks que cambiaron)
#   2. Corre aws cloudformation deploy con los parametros de dev
#
# Requisitos previos (una sola vez):
#   - Docker corriendo
#   - AWS SAM CLI >= 1.99.0  (brew install aws-sam-cli)
#   - Node.js 18.x            (nvm install 18)
#   - npm, pip3, zip, virtualenv
#   - AWS CLI configurado con credenciales de la cuenta dev
# =============================================================================
set -e

# ─── Configuración dev — editá estos valores si cambian ──────────────────────
STACK_NAME="agent-copilot-dev"
REGION="us-east-1"
CFN_BUCKET_BASENAME="lca-artifacts-strata"   # <-- completar con el bucket real
CFN_PREFIX="lca-dev"                          # <-- prefijo usado en el deploy original
PARAMETERS_FILE="strata-deploy-to-dev/lca-stack-parameters-dev.json"
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo ""
echo "============================================================"
echo "  Stack   : $STACK_NAME"
echo "  Región  : $REGION"
echo "  Bucket  : ${CFN_BUCKET_BASENAME}-${REGION}"
echo "  Prefix  : $CFN_PREFIX"
echo "============================================================"
echo ""

# ── Paso 1: Package ──────────────────────────────────────────────────────────
echo "▶ Paso 1/2: Packaging artefactos (solo sub-stacks modificados)..."
echo ""

cd "$ROOT_DIR"
./publish.sh "$CFN_BUCKET_BASENAME" "$CFN_PREFIX" "$REGION" || {
  echo ""
  echo "❌ publish.sh falló. Revisá el error arriba."
  exit 1
}

# ── Paso 2: Deploy ───────────────────────────────────────────────────────────
echo ""
echo "▶ Paso 2/2: Deployando stack CloudFormation..."
echo ""

VERSION=$(cat ./VERSION)
TEMPLATE_URL="https://s3.${REGION}.amazonaws.com/${CFN_BUCKET_BASENAME}-${REGION}/${CFN_PREFIX}/lca-main.yaml"

aws cloudformation deploy \
  --region "$REGION" \
  --template-url "$TEMPLATE_URL" \
  --stack-name "$STACK_NAME" \
  --parameter-overrides "$(jq -r '.[] | .ParameterKey + "=" + .ParameterValue' "$PARAMETERS_FILE" | tr '\n' ' ')" \
  --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --no-fail-on-empty-changeset

echo ""
echo "============================================================"
echo "  ✅ Deploy completado: $STACK_NAME"
echo "  Template: $TEMPLATE_URL"
echo "============================================================"
echo ""
