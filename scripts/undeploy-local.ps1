<# Remove the knowledge service. The Qdrant collection is left in place; see docs\runbook.md to drop it. #>
param([string]$Namespace = "aurai-knowledge")
helm uninstall aurai-knowledge -n $Namespace
kubectl delete secret knowledge-secrets -n $Namespace --ignore-not-found
kubectl delete namespace $Namespace --ignore-not-found
