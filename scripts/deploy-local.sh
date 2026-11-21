#!/usr/bin/env bash
# Build and install the Aurai knowledge service on the local kind cluster. Mirrors deploy-local.ps1.
# Requires: docker, kind, kubectl, helm, KNOWLEDGE_GATEWAY_KEY.
set -euo pipefail
CLUSTER="${CLUSTER:-aurai}"; NS="${NS:-aurai-knowledge}"; IMAGE="${IMAGE:-aurai-knowledge:0.1.0}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
for t in docker kind kubectl helm; do command -v "$t" >/dev/null || { echo "missing $t" >&2; exit 1; }; done
: "${KNOWLEDGE_GATEWAY_KEY:?set KNOWLEDGE_GATEWAY_KEY (see docs/local-development.md)}"

kubectl config use-context "kind-$CLUSTER" >/dev/null
docker build -t "$IMAGE" "$REPO"
kind load docker-image "$IMAGE" --name "$CLUSTER"

kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl label namespace "$NS" aurai.io/platform-access=true --overwrite >/dev/null
kubectl apply -f - >/dev/null <<YAML
apiVersion: v1
kind: Secret
metadata: { name: knowledge-secrets, namespace: $NS }
type: Opaque
stringData:
  AURAI_GATEWAY_KEY: "$KNOWLEDGE_GATEWAY_KEY"
YAML

helm upgrade --install aurai-knowledge "$REPO/charts/aurai-knowledge" -n "$NS" \
  -f "$REPO/charts/aurai-knowledge/values-local.yaml" \
  --set image.repository="${IMAGE%%:*}" --set image.tag="${IMAGE##*:}" \
  --set-file entitlements="$REPO/config/entitlements.yaml"

JOB="ingest-initial-$(date +%Y%m%d%H%M%S)"
kubectl create job "$JOB" --from=cronjob/aurai-knowledge-ingest -n "$NS" >/dev/null
if ! kubectl wait --for=condition=complete "job/$JOB" -n "$NS" --timeout=300s; then
  kubectl logs "job/$JOB" -n "$NS" --tail=40; echo "ingestion did not complete" >&2; exit 1
fi
kubectl logs "job/$JOB" -n "$NS" --tail=5
kubectl rollout status deployment/aurai-knowledge -n "$NS" --timeout=180s
echo "Done. Set the knowledge_service_url valve of the workspace tool to http://knowledge.$NS.svc.cluster.local:8000"
