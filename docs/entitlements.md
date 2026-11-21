# Entitlements

## The policy file

`config/entitlements.yaml` is the only place access is defined.

```yaml
grants:
  - group: knowledge-hr
    collections:
      hr-policies: restricted
```

A grant names a **classification ceiling** per collection. Order: `public < internal < confidential < restricted`. A caller reads a chunk only if its collection is granted and its classification is at or below the ceiling. Groups are the names in the token's `groups` claim (Keycloak group paths such as `/knowledge-hr` are normalised to `knowledge-hr`). A caller in several groups gets the union, with the highest ceiling per collection.

## Shipped policy

| Group | guest-services | ops-reports | hr-policies | finance-reporting |
|---|---|---|---|---|
| `workspace-members` | internal | - | internal | - |
| `workspace-builders` | internal | internal | internal | - |
| `knowledge-ops` | internal | confidential | - | - |
| `knowledge-hr` | - | - | restricted | - |
| `knowledge-finance` | - | - | - | restricted |
| `workspace-admins` | - | - | - | - |

`workspace-admins` has no row on purpose: managing the workspace does not grant access to business documents. Knowledge groups are created in the `aurai-workspace` realm and granted by the data owners.

## Classification of documents

- A collection declares a default in `collection.yaml`.
- A document may declare a higher one in front matter (`classification: restricted`). Declaring a lower one is an ingestion error, so a mislabelled file cannot widen access.
- Changing a collection default or a document's classification changes its hash, so the next ingestion rewrites its chunks.

## What the service never does

- Read identity from a request body. Unknown request fields are rejected with 422.
- Reveal that a forbidden passage or collection exists. Forbidden passages are omitted, not redacted, and a forbidden collection gets the same 403 as one that does not exist.
- Run a search with an empty entitlement. `entitlement_filter` raises, and the store will not query without one.

## Known limits

- Tokens are trusted until they expire (15 minutes in the workspace realm). Removing a user from a group takes effect at their next token.
- The audience check uses the workspace client's `litellm` audience because that is what the realm issues today. A dedicated `aurai-knowledge` audience would stop a token minted for the gateway from being replayed here; it needs a realm change and is listed in the README gaps.
- Response size and timing can differ between callers with different entitlements. This is not treated as a confidentiality boundary for the classifications used here.

## Changing the policy

1. Edit `config/entitlements.yaml` in a pull request reviewed by each affected data owner.
2. Add or update leak probes in `eval/golden-set.yaml` (a persona that must not see the new content).
3. `pytest` and `aurai-knowledge eval` must pass.
4. Redeploy. The chart mounts the file from a ConfigMap and rolls the pods when its checksum changes.
