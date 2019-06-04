# Crusher API Server

The API server that responds to slack webhooks and provides discovery endpoints
utilized by the corresponding [worker](https://github.com/jacobstr/reserver).

I was originally running this thing on a Raspberry PI under my couch, but I'm
a Cloud enthusiast now (I guess 🙄 ) and thougt it'd be a good hobby project.

# Development

The repo uses:

* minikube (v1.1.0): for a local development kube cluster.
* skaffold (v0.30.0): to tighten the build/deploy local development loop.
  Skaffold watches your code and kubernetes manifests for changes and continuosly
  updates your minikube as either your application, or it's deployment
  configuration changes.

The small [dev.sh](./dev.sh) script bootstraps the minikube docker environment
settings and runs skaffold for you.
