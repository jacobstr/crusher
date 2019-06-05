#!/bin/bash
kubectl config use-context minikube
source <(minikube docker-env -p minikube)
skaffold config set --kube-context minikube local-cluster true
skaffold dev
