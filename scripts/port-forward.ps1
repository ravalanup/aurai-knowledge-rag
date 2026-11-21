<# Port-forward the knowledge service to http://localhost:8000 for direct testing (docs\local-development.md). #>
param([string]$Namespace = "aurai-knowledge")
$ErrorActionPreference = "Stop"
Write-Host "Knowledge service http://localhost:8000   (Ctrl+C to stop)"
kubectl port-forward -n $Namespace svc/knowledge 8000:8000
