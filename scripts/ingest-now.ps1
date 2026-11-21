<# Run the ingestion job immediately (outside its schedule), for example after changing a document. #>
param([string]$Namespace = "aurai-knowledge")
$ErrorActionPreference = "Stop"
$job = "ingest-manual-" + (Get-Date -Format "yyyyMMddHHmmss")
kubectl create job $job --from=cronjob/aurai-knowledge-ingest -n $Namespace
kubectl wait --for=condition=complete "job/$job" -n $Namespace --timeout=300s
kubectl logs "job/$job" -n $Namespace --tail=20
