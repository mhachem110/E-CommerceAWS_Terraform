#!/usr/bin/env bash
set -euo pipefail

bash deploy/aws/install-kube-tools.sh
cluster_config="$(aws ssm get-parameter --name /retail-week3/dev/config --with-decryption --query Parameter.Value --output text)"
cluster="$(jq -r '.cluster_name' <<<"$cluster_config")"
region="$(jq -r '.region' <<<"$cluster_config")"
aws eks update-kubeconfig --name "$cluster" --region "$region"

if [[ "${DEPLOY_OPERATION:-deploy}" == "rollback" ]]; then
  helm -n retail rollback retail --wait --timeout 15m
  kubectl -n retail rollout status deployment/retail-storefront --timeout=5m
  helm -n retail history retail
  exit 0
fi

if [[ "${DEPLOY_OPERATION:-deploy}" == "failure-demo" ]]; then
  replicas="$(kubectl -n retail get deployment retail-product -o jsonpath='{.spec.replicas}')"
  restore() {
    kubectl -n retail scale deployment/retail-product --replicas="$replicas"
    kubectl -n retail rollout status deployment/retail-product --timeout=5m
  }
  trap restore EXIT
  kubectl -n retail scale deployment/retail-product --replicas=0
  kubectl -n retail rollout status deployment/retail-product --timeout=2m
  kubectl -n retail get deployment retail-product
  sleep 30
  echo "Restoring Product API after the controlled availability test"
  exit 0
fi

mkdir -p deploy/aws/generated
printf '%s' "$cluster_config" > deploy/aws/generated/config.json
python -m json.tool deploy/aws/generated/config.json >/dev/null

tag="${IMAGE_TAG:?IMAGE_TAG is required}"
python deploy/aws/render_values.py --config deploy/aws/generated/config.json \
  --tag "$tag" --output-dir deploy/aws/generated
kubectl -n retail create serviceaccount retail-db-bootstrap --dry-run=client -o yaml | kubectl apply -f -
kubectl -n retail delete job retail-db-bootstrap --ignore-not-found=true --wait=true
kubectl -n retail apply -f deploy/aws/generated/bootstrap-job.json
kubectl -n retail wait --for=condition=complete job/retail-db-bootstrap --timeout=10m

helm upgrade --install retail deploy/helm/retail --namespace retail \
  --values deploy/aws/generated/values.json --wait --atomic --timeout 15m
kubectl -n retail rollout status deployment/retail-storefront --timeout=5m

kubectl -n retail delete job retail-smoke --ignore-not-found=true --wait=true
smoke_image="$(jq -r '.ecr_repository_urls.product' deploy/aws/generated/config.json):${tag}"
kubectl -n retail create job retail-smoke --image="$smoke_image" -- python -m services.cloud_smoke
if ! kubectl -n retail wait --for=condition=complete job/retail-smoke --timeout=3m; then
  kubectl -n retail logs job/retail-smoke --all-containers=true
  exit 1
fi
kubectl -n retail logs job/retail-smoke
helm -n retail history retail
