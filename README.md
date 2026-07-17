# To-Do App — Infrastructure (CloudFormation)

All AWS infrastructure for the To-Do app: multi-AZ VPC, ECS Fargate, RDS PostgreSQL + RDS
Proxy, ElastiCache Redis, ALB, CodePipeline/CodeDeploy blue/green pipeline, EventBridge, and
the GitHub OIDC trust used by the [app repo](../todo-app-code)'s GitHub Actions workflow.

No NAT Gateway is used — private subnets reach ECR, CloudWatch Logs, Secrets Manager, and S3
purely through VPC endpoints, which is both cheaper and keeps ECS tasks fully private.

## Stack layout

| # | Stack | Template | Depends on |
|---|-------|----------|------------|
| 1 | `<env>-network`     | `templates/01-network.yaml`        | — |
| 2 | `<env>-security`    | `templates/02-security-groups.yaml`| network |
| 3 | `<env>-endpoints`   | `templates/03-vpc-endpoints.yaml`  | network, security |
| 4 | `<env>-data`        | `templates/04-data.yaml`           | network, security |
| 5 | `<env>-cache`       | `templates/05-cache.yaml`          | network, security |
| 6 | `<env>-compute`     | `templates/06-compute.yaml`        | network, security, data, cache |
| 7 | `<env>-pipeline`    | `templates/07-pipeline.yaml`       | compute |
| 8 | `<env>-github-oidc` | `templates/08-github-oidc.yaml`    | compute, pipeline |

Stacks are linked with `Export`/`Fn::ImportValue`, not nested-stack `TemplateURL`s, so each
one can be mapped as its own stack in **CloudFormation GitSync** without an S3 packaging step.

## First-time bootstrap (manual, before handing off to GitSync)

```bash
export GITHUB_ORG=<your-github-org-or-username>
export GITHUB_REPO=todo-app-code   # default
export AWS_REGION=us-east-1        # your region
./scripts/deploy.sh
```

This deploys stacks 1–8 in order. The ECS task definition initially runs a public placeholder
image (`httpd`) so the compute stack has something valid to launch — the real app image
replaces it the first time the GitHub Actions workflow in `todo-app-code` runs.

**Costs money as soon as it's applied**: RDS (Multi-AZ `db.t3.micro`), RDS Proxy, ElastiCache
(2 nodes), the ALB, 4 VPC interface endpoints, and CodePipeline all bill hourly. Tear down with
`aws cloudformation delete-stack` in reverse order when done.

## Wiring up the app repo after bootstrap

The `todo-app-code` GitHub Actions workflow needs these **Repository variables** (Settings →
Secrets and variables → Actions → Variables), copied from this stack's outputs:

| GitHub variable | Source |
|---|---|
| `AWS_REGION` | the region you deployed to |
| `AWS_DEPLOY_ROLE_ARN` | `<env>-github-oidc` stack output `GitHubActionsDeployRoleArn` |
| `ECR_REPOSITORY` | `<env>-compute` stack output `EcrRepositoryName` |
| `ARTIFACT_BUCKET` | `<env>-pipeline` stack output `ArtifactBucketName` |
| `ECS_EXECUTION_ROLE_ARN` | `<env>-compute` stack output `TaskExecutionRoleArn` |
| `ECS_TASK_ROLE_ARN` | `<env>-compute` stack output `TaskRoleArn` |
| `RDS_PROXY_ENDPOINT` | `<env>-data` stack output `RdsProxyEndpoint` |
| `DB_NAME` | `<env>-data` stack output `DBName` |
| `DB_SECRET_ARN` | `<env>-data` stack output `DBSecretArn` |
| `REDIS_HOST` | `<env>-cache` stack output `RedisPrimaryEndpointAddress` |
| `REDIS_PORT` | `<env>-cache` stack output `RedisPrimaryEndpointPort` |
| `LOG_GROUP` | `/ecs/<env>` (e.g. `/ecs/todo-app`) |

Once those are set, a push to `main` in `todo-app-code` builds the image, pushes it to ECR,
uploads the blue/green deploy bundle to S3, and the ECR push itself fires the EventBridge
rule that starts CodePipeline → CodeDeploy.

## Handing off to CloudFormation GitSync

After the manual bootstrap above succeeds once (so all cross-stack exports exist), connect
this repo in the CloudFormation console (**Git sync** → connect via CodeConnections to GitHub)
and create one sync configuration per stack, each pointing at its template file and using the
same stack name you bootstrapped with. From then on, template changes pushed to this repo
apply automatically — deploy order still matters on first sync, so sync `network` →
`security` → `endpoints` → `data`/`cache` → `compute` → `pipeline` → `github-oidc`.

## Tagging

`scripts/deploy.sh` passes `--tags Project=<env> Environment=<deploy_env> ManagedBy=CloudFormation`
on every `aws cloudformation deploy` call. CloudFormation propagates stack-level tags to every
resource in the stack that supports tagging, so this covers the whole stack without per-resource
`Tags:` blocks. Reproduce the same `--tags` when configuring each CloudFormation GitSync stack.

## Architecture diagram

See [`diagrams/architecture.py`](diagrams/architecture.py) (diagram-as-code, using the
`diagrams` Python library) and its rendered [`diagrams/architecture.png`](diagrams/architecture.png).
