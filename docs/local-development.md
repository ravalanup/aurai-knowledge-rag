# Local development

## Without a cluster

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q
aurai-knowledge validate-corpus --source corpus
aurai-knowledge eval
```

Everything runs in memory: Qdrant through `qdrant-client`'s local mode, and a deterministic embedder. No network, no keys.

## On the kind cluster

Order matters because each repo builds on the previous ones.

1. `aurai-infra`: cluster up (Qdrant, Keycloak, Postgres, collector).
2. `aurai-gateway`: deployed, with the `aurai-embed` alias backed by a real model (`docs/embeddings.md`).
3. `aurai-workspace`: realm applied (it now includes the `knowledge-*` groups and three demo users).
4. Apply the gateway team and issue a key:

```powershell
aurai-teamctl apply gateway\knowledge-team.yaml --catalog ..\aurai-gateway\config\model-catalog.yaml --base-url http://localhost:4000
aurai-teamctl issue-key knowledge --teams gateway\knowledge-team.yaml --catalog ..\aurai-gateway\config\model-catalog.yaml --base-url http://localhost:4000 --alias knowledge-service
```

5. Deploy (builds the image, installs the chart, runs the first ingestion):

```powershell
$env:KNOWLEDGE_GATEWAY_KEY = "<key from step 4>"
.\scripts\deploy-local.ps1
```

If the ingestion job fails, the script prints its log. The usual causes are an `aurai-embed` alias that is not enabled, a wrong key, or Ollama not reachable from the cluster.

6. In Open WebUI (as an admin), open the `knowledge_search` tool and set its `knowledge_service_url` valve to `http://knowledge.aurai-knowledge.svc.cluster.local:8000`.
7. Sign in as different demo users and ask the same question. `priya.nair` can find the Q3 revenue summary; `maya.ortega` cannot.

## Calling the service directly

```powershell
.\scripts\port-forward.ps1
$token = .\scripts\get-token.ps1 -Username priya.nair -ClientId <test-client> -ClientSecret <secret>
Invoke-RestMethod -Method Post http://localhost:8000/v1/search -Headers @{Authorization = "Bearer $token"} `
  -ContentType application/json -Body '{"query":"What was Q3 revenue?","top_k":3}'
```

The workspace client has direct grants off on purpose; use a separate test client in a non-production realm (see the header of `get-token.ps1`). The issuer in the token must equal `config.oidcIssuer`, so call Keycloak with the same hostname the pods use (the hosts-file entry from the workspace docs).

## Changing documents

Edit files under `corpus/`, rebuild the image (`deploy-local.ps1` again) and run `scripts\ingest-now.ps1`. In AWS the source is S3, so no rebuild is needed.
