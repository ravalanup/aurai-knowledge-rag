# Contributing

## Set up

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Before you open a pull request

```powershell
ruff check .
ruff format --check .
pytest -q
aurai-knowledge validate-corpus --source corpus
aurai-knowledge eval
```

CI runs the same commands, plus `helm lint`, `helm template` with kubeconform, a container build and secret scanning.

## Rules that protect the entitlement model

- **Every search goes through `QdrantStore.search`**, which builds its filter from an `Entitlement` and refuses an empty one. Do not call the Qdrant client for retrieval anywhere else.
- **Identity comes from the verified token.** Never read groups, roles or a user id from a request body, header or query string. The request schema forbids unknown fields on purpose.
- **Changes to `config/entitlements.yaml`** need a reviewer from the data owner for every collection they touch. Add a leak probe to `eval/golden-set.yaml` for each new grant.
- **A new collection** needs a `collection.yaml` with `team`, `owner` and `classification`, an entry in `config/entitlements.yaml`, and at least one golden-set case.
- **Do not log or trace query text or passage text.** Tests assert this.
- Keep sample documents synthetic. No real names, customer data or internal documents.

## Commit messages

Imperative mood, a short summary line, and a body that says why when it is not obvious.
