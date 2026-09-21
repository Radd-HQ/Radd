{{- define "radd.name" -}}
{{ .Chart.Name }}
{{- end }}

{{- define "radd.labels" -}}
app.kubernetes.io/name: {{ include "radd.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "radd.image" -}}
{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}
{{- end }}

{{- define "radd.env" -}}
{{- range $key, $value := .Values.env }}
{{- if $value }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}
{{- end }}
{{- /* A script's ctx.client (RADD-1277) calls the in-cluster Service rather
       than hairpinning through the ingress — the worker pod may not be able
       to reach the public name at all. `env.RADD_SCRIPTS_API_URL` overrides. */}}
{{- if not .Values.env.RADD_SCRIPTS_API_URL }}
- name: RADD_SCRIPTS_API_URL
  value: {{ printf "http://%s:%v" .Release.Name .Values.service.port | quote }}
{{- end }}
{{- end }}

{{- define "radd.envFrom" -}}
{{- if .Values.envFromSecret }}
envFrom:
  - secretRef:
      name: {{ .Values.envFromSecret }}
{{- end }}
{{- end }}

{{/*
Fail the render when a key is set BOTH in `env` and (by intent) in the Secret.
Kubernetes resolves that conflict by letting the container's `env` entry win
over anything arriving via `envFrom` — so a passwordless RADD_DATABASE_URL left
in values.yaml "for documentation" silently overrides the real one and the app
dies with "no password supplied". Caught here instead of in a CrashLoopBackOff.
*/}}
{{- define "radd.validate" -}}
{{- if and .Values.envFromSecret .Values.env.RADD_DATABASE_URL }}
{{/* "://user@host" (no colon in the userinfo) = no password in the URL. */}}
{{- if regexMatch "://[^:@/]+@" (toString .Values.env.RADD_DATABASE_URL) }}
{{- fail "values.env.RADD_DATABASE_URL carries no password while envFromSecret is set. A container's `env` entry TAKES PRECEDENCE over the same key from `envFrom`, so this value would override the credentialed URL in the Secret and the app would fail with 'no password supplied'. Remove RADD_DATABASE_URL from values.env and keep it only in the Secret." }}
{{- end }}
{{- end }}
{{- end }}

{{- define "radd.imagePullSecrets" -}}
{{- with .Values.imagePullSecrets }}
imagePullSecrets:
{{- range . }}
  - name: {{ . }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Volume mounts and volumes for the app containers. Two SEPARATE claims by
design: /data holds attachments plus the backup encryption key, while backup
artifacts live on their own volume — docs/deploy.md's rule that the key must be
recoverable independently of the artifacts only holds if they can't be lost
together. The migrate Job mounts neither (it only touches the database).
*/}}
{{- define "radd.volumeMounts" -}}
volumeMounts:
  - name: plugins
    mountPath: /data/plugins
{{- if not .Values.storage.s3 }}
  - name: data
    mountPath: /data
{{- end }}
{{- if .Values.backups.enabled }}
  - name: backups
    mountPath: {{ .Values.backups.mountPath }}
{{- end }}
{{- end }}

{{- define "radd.volumes" -}}
volumes:
  - name: plugins
    persistentVolumeClaim:
      claimName: {{ .Release.Name }}-plugins
{{- if not .Values.storage.s3 }}
  - name: data
    persistentVolumeClaim:
      claimName: {{ .Release.Name }}-data
{{- end }}
{{- if .Values.backups.enabled }}
  - name: backups
    persistentVolumeClaim:
      claimName: {{ .Release.Name }}-backups
{{- end }}
{{- end }}
