#!/bin/bash
source <(minikube docker-env -p minikube)
skaffold config set --kube-context minikube local-cluster true
