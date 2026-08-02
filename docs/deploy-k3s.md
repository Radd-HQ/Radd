# Deploying Radd on k3s

A barebones single-node walkthrough for the Helm chart in `deploy/helm/radd`.
`docs/deploy.md` is the general deployment reference (backups, storage,
embeddings, the environment table); this covers what k3s specifically needs.

Sample configs live in `deploy/k3s/` — copy them somewhere outside this repo
and edit there. A real deployment's values carry your hostnames, network
addresses and secrets; they belong with your infrastructure, not the
application.

## 1. k3s

```bash
curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
```

If you're putting Radd behind an **existing** reverse proxy (one public IP,
`:443` already spoken for), pin Traefik's HTTP entrypoint to a stable NodePort
so the outer proxy has a fixed address:

```yaml
# /var/lib/rancher/k3s/server/manifests/traefik-config.yaml
apiVersion: helm.cattle.io/v1
kind: HelmChart
metadata:
  name: traefik
  namespace: kube-system
spec:
  repo: https://traefik.github.io/charts
  chart: traefik
  targetNamespace: kube-system
  valuesContent: |-
    service:
      type: NodePort
    ports:
      web:
        nodePort: 30080
      websecure:
        expose:
          default: false   # TLS terminates at the outer proxy
```

Then `deploy/k3s/Caddyfile.chain.example` shows the outer half.

## 2. PostgreSQL

The chart ships no database. CloudNativePG is the straightforward choice:

```bash
kubectl apply --server-side -f \
  https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.24/releases/cnpg-1.24.0.yaml
kubectl -n cnpg-system rollout status deploy/cnpg-controller-manager
```

`deploy/k3s/postgres-cnpg-example.yaml` is a working Cluster. Two things that
cost time if missed:

- The bootstrap Secret **must be `kubernetes.io/basic-auth`**. An Opaque secret
  with `username`/`password` keys is silently not accepted.
- **pgvector**: stock CNPG images don't ship it. Build
  `deploy/k3s/pgvector.Containerfile` and import it, or run upstream and let
  search stay plain FTS — semantic search is a soft dependency (spec 103),
  nothing else changes.

Radd's app role needs `SUPERUSER` only because `CREATE EXTENSION vector` does;
the guarded migration runs it at startup.

## 3. Images without a registry

Building on the node and importing avoids standing up a registry first:

```bash
podman build -f Containerfile -t radd:0.1.0 .
podman save localhost/radd:0.1.0 -o /tmp/radd.tar
sudo k3s ctr images import /tmp/radd.tar
```

Keep the `localhost/` prefix in `image.repository`. Podman tags unqualified
builds that way, containerd stores that exact name, and a bare `radd` resolves
to `docker.io/library/radd` and fails to pull. Pair it with
`pullPolicy: IfNotPresent`.

For a private registry later, `imagePullSecrets` is applied to the web pods,
the worker pod, and the migration Job.

## 4. Storage

The chart creates **two** PVCs and both matter:

| Claim | Holds |
|---|---|
| `<release>-data` | attachments + the backup **encryption key** |
| `<release>-backups` | backup artifacts |

They are separate so one lost volume can't take both. Put
`backups.storageClassName` on a different disk from the database —
`deploy/k3s/backups-storageclass-example.yaml` does that with a second device.

Both claims are **ReadWriteOnce** and are mounted by the web *and* worker pods:
the nightly dump runs wherever `RADD_RUN_WORKERS` is true (the worker, once
split), while restores are driven from the web tier. That works on one node
because both pods land there. Adding nodes means RWX or node affinity first.

`podSecurityContext.fsGroup: 10001` is set by default to match the image's
`USER radd`; without it the volumes mount root-owned and nothing can be
written.

## 5. Install

```bash
kubectl create namespace radd
kubectl -n radd create secret generic radd-secrets --from-env-file=my-secrets.env
helm upgrade --install radd deploy/helm/radd -n radd -f my-values.yaml
kubectl -n radd rollout status deploy/radd-web
```

Migrations run as a pre-install/pre-upgrade hook Job — `kubectl -n radd get
jobs` if a release seems to hang.

Create the first admin:

```bash
kubectl -n radd exec deploy/radd-web -- \
  python -m radd.seed --email you@example.com --password '<strong>' --name "You"
```

> If you plan to use SSO (spec 110), seed this admin with **the address you'll
> sign in with**. A provider that carries no `admin_groups` has no authority to
> grant a role, so the first SSO sign-in would create a plain member. Seeding
> first means the SSO login *links* to the existing admin account and keeps its
> role — verified email on first login, pinned to the provider's subject after.

## 6. Proxy headers

`RADD_TRUSTED_PROXIES` must list **every** hop. `clientip.py` walks
`X-Forwarded-For` right-to-left and returns the first untrusted entry, so
behind an outer proxy in front of Traefik you need its address *and* the pod
CIDR (`10.42.0.0/16` by default). Miss one and every request appears to come
from the proxy — which breaks storage CIDR routing rules and audit attribution.

Never list ranges end users can occupy: a trusted peer's XFF is believed.

## Upgrades and rollback

```bash
helm upgrade radd deploy/helm/radd -n radd -f my-values.yaml \
  --set image.tag=0.2.0
```

The migration hook runs before the new pods. `helm rollback radd` reverses the
release, but **not** the migration — for anything schema-breaking, restore from
a backup or a VM snapshot instead. Restores are single-node and single-replica:
scale web to 1 first (see `docs/deploy.md`).

## Object storage: two Garage instances (spec 102)

`garage.yaml` in the deployment repo runs **two independent single-node Garage
instances** — `garage-content` and `garage-general` — each with its own 20Gi
volume, bucket and credentials.

Two instances, not one replicated cluster, and the reason matters: this is a
single-node box. Two Garage nodes replicating to each other would write both
copies to the same disk. What two hosts actually buy is Radd's routing chain —
content routed to one, general uploads to the other, each with its own lifecycle.

```bash
# CD applies the manifests; the buckets and keys are a ONE-SHOT, on the host:
GARAGE_ACCESS_KEY=GK... GARAGE_SECRET_KEY=... ./garage-init.sh garage-content
GARAGE_ACCESS_KEY=GK... GARAGE_SECRET_KEY=... ./garage-init.sh garage-general
```

Then register each in **Settings → Storage** as an `s3` host:

| | |
|---|---|
| endpoint | `garage-content.radd.svc.cluster.local:3900` |
| bucket | `radd-content` / `radd-general` |
| region | `garage` — **must** match `s3_region` in `garage.yaml` |
| secure | off (plain HTTP inside the cluster) |
| delivery | proxy |

A region mismatch does not report itself as a region mismatch: it surfaces as an
opaque signature error. That is the first thing to check when uploads fail.

Delivery is **proxy** deliberately — bytes flow through the app, which is what
keeps spec-102 per-attachment read grants enforceable at a single seam.
Presigned delivery would need a public S3 hostname per host, plus TLS and CORS.
