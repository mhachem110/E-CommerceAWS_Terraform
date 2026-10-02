#!/usr/bin/env bash
set -euo pipefail

bash deploy/aws/install-kube-tools.sh
cluster_config="$(aws ssm get-parameter --name /retail-week3/dev/config --with-decryption --query Parameter.Value --output text)"
cluster="$(jq -r '.cluster_name' <<<"$cluster_config")"
region="$(jq -r '.region' <<<"$cluster_config")"
aws eks update-kubeconfig --name "$cluster" --region "$region"
for attempt in $(seq 1 24); do
  if kubectl -n retail get serviceaccount default >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 24 ]]; then
    echo "EKS namespace access was not ready after four minutes" >&2
    exit 1
  fi
  sleep 10
done

run_smoke() {
  local image="$1"
  kubectl -n retail delete job retail-smoke --ignore-not-found=true --wait=true
  kubectl -n retail create job retail-smoke --image="$image" -- python -m services.cloud_smoke
  if ! kubectl -n retail wait --for=condition=complete job/retail-smoke --timeout=3m; then
    kubectl -n retail logs job/retail-smoke --all-containers=true
    return 1
  fi
  kubectl -n retail logs job/retail-smoke
}

current_product_image() {
  helm -n retail get values retail --output json |
    jq -er '.services[] | select(.name == "product") | .image'
}

if [[ "${DEPLOY_OPERATION:-deploy}" == "rollback" ]]; then
  helm -n retail rollback retail --wait --timeout 15m
  kubectl -n retail rollout status deployment/retail-storefront --timeout=5m
  run_smoke "$(current_product_image)"
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
  for attempt in $(seq 1 12); do
    endpoints="$(kubectl -n retail get endpoints retail-product -o jsonpath='{.subsets[*].addresses[*].ip}')"
    if [[ -z "$endpoints" ]]; then
      break
    fi
    sleep 5
  done
  test -z "$endpoints"
  echo "Failure verified: Product Service has no ready endpoints"
  sleep 30
  echo "Restoring Product API after the controlled availability test"
  restore
  trap - EXIT
  run_smoke "$(current_product_image)"
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

previous_revision="$(helm -n retail list --all --output json | jq -r '.[] | select(.name == "retail") | .revision')"
helm upgrade --install retail deploy/helm/retail --namespace retail \
  --values deploy/aws/generated/values.json --wait --atomic --timeout 15m
kubectl -n retail rollout status deployment/retail-storefront --timeout=5m

smoke_image="$(jq -r '.ecr_repository_urls.product' deploy/aws/generated/config.json):${tag}"
if ! run_smoke "$smoke_image"; then
  if [[ -n "$previous_revision" ]]; then
    echo "Smoke failed; rolling back to Helm revision $previous_revision" >&2
    helm -n retail rollback retail "$previous_revision" --wait --timeout 15m
  fi
  exit 1
fi
helm -n retail history retail
