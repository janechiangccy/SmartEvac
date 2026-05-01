#!/usr/bin/env bash
# SmartEvac — 一次性建立 IoT Thing / Cert / Policy，並把憑證下載到 ./certs
# Idempotent：每步先檢查存在，存在就跳過。重跑不會炸。
#
# 前置：. ../.env（Learner Lab AWS creds 已 export）
# 執行：bash setup_iot_thing.sh

set -euo pipefail

THING_NAME="smartevac-subscriber"
POLICY_NAME="SmartEvacSubscriberPolicy"
CERT_DIR="$(cd "$(dirname "$0")" && pwd)/certs"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

mkdir -p "$CERT_DIR"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "▶ Account: $ACCOUNT_ID  Region: $REGION"

# ─── 1) IoT Thing ─────────────────────────────────────────────────────
if aws iot describe-thing --thing-name "$THING_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "✓ Thing 已存在：$THING_NAME"
else
  echo "▶ 建立 Thing：$THING_NAME"
  aws iot create-thing --thing-name "$THING_NAME" --region "$REGION" >/dev/null
fi

# ─── 2) Certificate ───────────────────────────────────────────────────
CERT_FILE="$CERT_DIR/device.pem.crt"
KEY_FILE="$CERT_DIR/private.pem.key"
CERT_ARN_FILE="$CERT_DIR/cert.arn"

if [[ -f "$CERT_FILE" && -f "$KEY_FILE" && -f "$CERT_ARN_FILE" ]]; then
  CERT_ARN=$(cat "$CERT_ARN_FILE")
  echo "✓ Certificate 已存在：$CERT_ARN"
else
  echo "▶ 建立新 Certificate（含 keypair）"
  CERT_JSON=$(aws iot create-keys-and-certificate \
    --set-as-active \
    --region "$REGION")
  CERT_ARN=$(echo "$CERT_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin)['certificateArn'])")
  echo "$CERT_ARN" > "$CERT_ARN_FILE"
  echo "$CERT_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin)['certificatePem'])" > "$CERT_FILE"
  echo "$CERT_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin)['keyPair']['PrivateKey'])" > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
  echo "  ✓ 已存：$CERT_FILE / $KEY_FILE"
fi

# ─── 3) Amazon Root CA ────────────────────────────────────────────────
CA_FILE="$CERT_DIR/AmazonRootCA1.pem"
if [[ -f "$CA_FILE" ]]; then
  echo "✓ Root CA 已存在"
else
  echo "▶ 下載 Amazon Root CA"
  curl -sf https://www.amazontrust.com/repository/AmazonRootCA1.pem -o "$CA_FILE"
fi

# ─── 4) IoT Policy ────────────────────────────────────────────────────
POLICY_DOC=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["iot:Connect"],
      "Resource": "arn:aws:iot:${REGION}:${ACCOUNT_ID}:client/smartevac-*"
    },
    {
      "Effect": "Allow",
      "Action": ["iot:Subscribe"],
      "Resource": "arn:aws:iot:${REGION}:${ACCOUNT_ID}:topicfilter/smartevac/cmd/*"
    },
    {
      "Effect": "Allow",
      "Action": ["iot:Receive"],
      "Resource": "arn:aws:iot:${REGION}:${ACCOUNT_ID}:topic/smartevac/cmd/*"
    }
  ]
}
EOF
)

if aws iot get-policy --policy-name "$POLICY_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "✓ Policy 已存在：$POLICY_NAME"
else
  echo "▶ 建立 Policy：$POLICY_NAME"
  aws iot create-policy \
    --policy-name "$POLICY_NAME" \
    --policy-document "$POLICY_DOC" \
    --region "$REGION" >/dev/null
fi

# ─── 5) Attach Policy → Cert ──────────────────────────────────────────
ATTACHED_POLICIES=$(aws iot list-attached-policies --target "$CERT_ARN" --region "$REGION" --query "policies[].policyName" --output text)
if echo "$ATTACHED_POLICIES" | grep -qw "$POLICY_NAME"; then
  echo "✓ Policy 已 attach 到 Certificate"
else
  echo "▶ Attach Policy → Certificate"
  aws iot attach-policy --policy-name "$POLICY_NAME" --target "$CERT_ARN" --region "$REGION"
fi

# ─── 6) Attach Cert → Thing ───────────────────────────────────────────
ATTACHED_THINGS=$(aws iot list-principal-things --principal "$CERT_ARN" --region "$REGION" --query "things" --output text)
if echo "$ATTACHED_THINGS" | grep -qw "$THING_NAME"; then
  echo "✓ Certificate 已 attach 到 Thing"
else
  echo "▶ Attach Certificate → Thing"
  aws iot attach-thing-principal --thing-name "$THING_NAME" --principal "$CERT_ARN" --region "$REGION"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "✅ IoT 訂閱端設置完成"
echo "═══════════════════════════════════════════════════════════════"
echo "  Thing:    $THING_NAME"
echo "  Cert ARN: $CERT_ARN"
echo "  Policy:   $POLICY_NAME"
echo "  Certs:    $CERT_DIR/"
echo ""
echo "下一步在 3 個 terminal 各跑一個節點："
echo "  NODE_ID=N1 python3 subscriber.py"
echo "  NODE_ID=N2 python3 subscriber.py"
echo "  NODE_ID=N3 python3 subscriber.py"
