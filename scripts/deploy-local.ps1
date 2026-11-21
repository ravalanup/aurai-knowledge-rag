<#
.SYNOPSIS
  Build and install the Aurai knowledge service on the local kind cluster, then run the first ingestion.

.DESCRIPTION
  Prerequisites
    - aurai-infra running (Qdrant, Keycloak, Postgres) and aurai-gateway deployed with an embedding model behind
      the aurai-embed alias (see docs\embeddings.md), the "knowledge" team applied and a key issued.
    - Docker, kind, kubectl, helm. Pass the key with -GatewayKey or $env:KNOWLEDGE_GATEWAY_KEY.
  What it does
    1. Builds the image and loads it into kind.
    2. Creates the namespace (labelled for platform access) and the knowledge-secrets Secret (from stdin).
    3. Installs the chart with the entitlement policy from config\entitlements.yaml.
    4. Runs the ingestion job once and waits for it, then waits for the service to be ready.
  The service stays not-ready until the first ingestion creates the index, so the chart is installed without --wait.
#>
param(
  [string]$ClusterName = "aurai",
  [string]$Namespace = "aurai-knowledge",
  [string]$Image = "aurai-knowledge:0.1.0",
  [string]$GatewayKey = $env:KNOWLEDGE_GATEWAY_KEY
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

foreach ($tool in "docker", "kind", "kubectl", "helm") {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing required tool: $tool" }
}
if (-not $GatewayKey) { throw "No gateway key. Issue one for the knowledge team (docs\local-development.md) and pass -GatewayKey." }

kubectl config use-context "kind-$ClusterName" | Out-Null

Write-Host "Building $Image"
docker build -t $Image $repo
if ($LASTEXITCODE -ne 0) { throw "docker build failed" }
kind load docker-image $Image --name $ClusterName
if ($LASTEXITCODE -ne 0) { throw "kind load failed" }

kubectl create namespace $Namespace --dry-run=client -o yaml | kubectl apply -f - | Out-Null
kubectl label namespace $Namespace aurai.io/platform-access=true --overwrite | Out-Null

@"
apiVersion: v1
kind: Secret
metadata: { name: knowledge-secrets, namespace: $Namespace }
type: Opaque
stringData:
  AURAI_GATEWAY_KEY: "$GatewayKey"
"@ | kubectl apply -f - | Out-Null

$repository, $tag = $Image.Split(":")
helm upgrade --install aurai-knowledge "$repo\charts\aurai-knowledge" -n $Namespace `
  -f "$repo\charts\aurai-knowledge\values-local.yaml" `
  --set image.repository=$repository --set image.tag=$tag `
  --set-file entitlements="$repo\config\entitlements.yaml"
if ($LASTEXITCODE -ne 0) { throw "helm install failed" }

$job = "ingest-initial-" + (Get-Date -Format "yyyyMMddHHmmss")
Write-Host "Running the first ingestion ($job)"
kubectl create job $job --from=cronjob/aurai-knowledge-ingest -n $Namespace | Out-Null
kubectl wait --for=condition=complete "job/$job" -n $Namespace --timeout=300s
if ($LASTEXITCODE -ne 0) {
  kubectl logs "job/$job" -n $Namespace --tail=40
  throw "Ingestion did not complete. The log above usually names the cause (gateway key, embedding model, Qdrant)."
}
kubectl logs "job/$job" -n $Namespace --tail=5
kubectl rollout status deployment/aurai-knowledge -n $Namespace --timeout=180s
Write-Host "Done. Set the knowledge_service_url valve of the workspace tool to http://knowledge.$Namespace.svc.cluster.local:8000"
