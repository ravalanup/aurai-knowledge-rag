{{- define "aurai-knowledge.labels" -}}
app.kubernetes.io/part-of: aurai
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
aurai.io/environment: {{ .Values.global.environment | quote }}
{{- end -}}

{{- define "aurai-knowledge.selector" -}}
app.kubernetes.io/name: aurai-knowledge
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "aurai-knowledge.image" -}}
{{ required "image.repository must be set" .Values.image.repository }}:{{ .Values.image.tag }}
{{- end -}}

{{/* Environment shared by the API and the ingestion job. */}}
{{- define "aurai-knowledge.env" -}}
- name: AURAI_QDRANT_URL
  value: {{ .Values.config.qdrantUrl | quote }}
- name: AURAI_QDRANT_COLLECTION
  value: {{ .Values.config.qdrantCollection | quote }}
- name: AURAI_GATEWAY_URL
  value: {{ .Values.config.gatewayUrl | quote }}
- name: AURAI_EMBED_MODEL
  value: {{ .Values.config.embedModel | quote }}
- name: AURAI_EMBED_BATCH_SIZE
  value: {{ .Values.config.embedBatchSize | quote }}
- name: AURAI_EMBED_DIMENSIONS
  value: {{ .Values.config.embedDimensions | quote }}
- name: AURAI_OIDC_ISSUER
  value: {{ .Values.config.oidcIssuer | quote }}
- name: AURAI_OIDC_JWKS_URL
  value: {{ .Values.config.oidcJwksUrl | quote }}
- name: AURAI_OIDC_AUDIENCE
  value: {{ .Values.config.oidcAudience | quote }}
- name: AURAI_MIN_SCORE
  value: {{ .Values.config.minScore | quote }}
- name: AURAI_OTLP_ENDPOINT
  value: {{ .Values.config.otlpEndpoint | quote }}
- name: AURAI_USE_CASE_ID
  value: {{ .Values.config.useCaseId | quote }}
- name: AURAI_TEAM_ID
  value: {{ .Values.config.teamId | quote }}
- name: AURAI_RISK_TIER
  value: {{ .Values.config.riskTier | quote }}
- name: AURAI_ENTITLEMENTS_FILE
  value: /etc/aurai/entitlements.yaml
- name: AURAI_GATEWAY_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.gatewayKey.name }}
      key: {{ .Values.secrets.gatewayKey.key }}
{{- if .Values.secrets.qdrantApiKey.name }}
- name: AURAI_QDRANT_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.qdrantApiKey.name }}
      key: {{ .Values.secrets.qdrantApiKey.key }}
{{- end }}
{{- end -}}

{{- define "aurai-knowledge.securityContext" -}}
runAsNonRoot: true
runAsUser: 10001
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
seccompProfile:
  type: RuntimeDefault
{{- end -}}
