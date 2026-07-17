#!/usr/bin/env bash
# Sequential local/manual deploy of the To-Do app infrastructure stacks.
# Intended for first-time bootstrap and local testing; once the exports
# exist, CloudFormation GitSync can take over day-to-day updates per stack.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ENV_NAME="${ENV_NAME:-todo-app}"
DEPLOY_ENV="${DEPLOY_ENV:-production}"
GITHUB_ORG="${GITHUB_ORG:?Set GITHUB_ORG to your GitHub org/username}"
GITHUB_REPO="${GITHUB_REPO:-todo-app-code}"

TEMPLATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../templates" && pwd)"

deploy_stack() {
  local stack_name="$1"
  local template_file="$2"
  shift 2
  echo "==> Deploying ${stack_name}"
  aws cloudformation deploy \
    --region "${REGION}" \
    --stack-name "${stack_name}" \
    --template-file "${TEMPLATE_DIR}/${template_file}" \
    --capabilities CAPABILITY_NAMED_IAM \
    --tags Project="${ENV_NAME}" Environment="${DEPLOY_ENV}" ManagedBy=CloudFormation \
    --parameter-overrides EnvironmentName="${ENV_NAME}" "$@"
}

deploy_stack "${ENV_NAME}-network"      01-network.yaml
deploy_stack "${ENV_NAME}-security"     02-security-groups.yaml
deploy_stack "${ENV_NAME}-endpoints"    03-vpc-endpoints.yaml
deploy_stack "${ENV_NAME}-data"         04-data.yaml
deploy_stack "${ENV_NAME}-cache"        05-cache.yaml
deploy_stack "${ENV_NAME}-compute"      06-compute.yaml
deploy_stack "${ENV_NAME}-pipeline"     07-pipeline.yaml
deploy_stack "${ENV_NAME}-github-oidc"  08-github-oidc.yaml \
  GitHubOrg="${GITHUB_ORG}" GitHubRepo="${GITHUB_REPO}"

echo "==> Done. ALB DNS name:"
aws cloudformation describe-stacks \
  --region "${REGION}" \
  --stack-name "${ENV_NAME}-compute" \
  --query "Stacks[0].Outputs[?OutputKey=='AlbDnsName'].OutputValue" \
  --output text
