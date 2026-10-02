#!/usr/bin/env bash
set -euo pipefail

kubectl_version=v1.34.0
helm_version=v3.18.4
tools_dir="${TMPDIR:-/tmp}/retail-tools"
mkdir -p "$tools_dir"

curl -fsSL "https://dl.k8s.io/release/${kubectl_version}/bin/linux/amd64/kubectl" -o "$tools_dir/kubectl"
curl -fsSL "https://dl.k8s.io/release/${kubectl_version}/bin/linux/amd64/kubectl.sha256" -o "$tools_dir/kubectl.sha256"
printf '%s  %s\n' "$(cat "$tools_dir/kubectl.sha256")" "$tools_dir/kubectl" | sha256sum --check --status
install -m 0755 "$tools_dir/kubectl" /usr/local/bin/kubectl

curl -fsSL "https://get.helm.sh/helm-${helm_version}-linux-amd64.tar.gz" -o "$tools_dir/helm.tgz"
curl -fsSL "https://get.helm.sh/helm-${helm_version}-linux-amd64.tar.gz.sha256sum" -o "$tools_dir/helm.sha256sum"
expected="$(awk '{print $1}' "$tools_dir/helm.sha256sum")"
printf '%s  %s\n' "$expected" "$tools_dir/helm.tgz" | sha256sum --check --status
tar -xzf "$tools_dir/helm.tgz" -C "$tools_dir"
install -m 0755 "$tools_dir/linux-amd64/helm" /usr/local/bin/helm
