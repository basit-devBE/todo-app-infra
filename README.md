# To-Do App — Infrastructure (CloudFormation)

All AWS infrastructure for the To-Do app: multi-AZ VPC, ECS Fargate, RDS PostgreSQL + RDS
Proxy, ElastiCache Redis, ALB, CodePipeline/CodeDeploy blue/green pipeline, EventBridge, and
the GitHub OIDC trust used by the [app repo](../todo-app-code)'s GitHub Actions workflow.

No NAT Gateway is used — private subnets reach ECR, CloudWatch Logs, Secrets Manager, and S3
purely through VPC endpoints, which is both cheaper and keeps ECS tasks fully private.

Deployed via **CloudFormation Git sync**, not a CLI script — GitSync only tracks one root
template per stack, so this repo uses the standard nested-stack pattern: `root-stack.yaml` at
the repo root composes nine child stacks in `stacks/`, each nested stack's `TemplateURL`
pointing at an S3 bucket that mirrors this repo's `stacks/` folder.

## Layout

| Path | Purpose |
|---|---|
| `root-stack.yaml` | The template GitSync actually tracks — wires all child stacks together |
| `deployment-file.yaml` | GitSync's stack deployment file: parameters, capabilities, tags for `root-stack.yaml` |
| `stacks/network.yaml` | VPC, public subnets (ALB), three private subnet tiers (ECS / data / cache), VPC endpoints |
| `stacks/security.yaml` | Six security groups, chained ALB → ECS → RDS Proxy → RDS, and ECS → Redis |
| `stacks/database.yaml` | RDS PostgreSQL (`db.t3`, Multi-AZ), Secrets Manager credentials, RDS Proxy |
| `stacks/cache.yaml` | ElastiCache Redis replication group (primary + replica) |
| `stacks/ecr.yaml` | ECR repository for the app image |
| `stacks/iam.yaml` | GitHub Actions role (existing OIDC provider), ECS execution/task roles |
| `stacks/compute.yaml` | ECS cluster, ALB (prod + test listener), blue/green target groups, task definition, service |
| `stacks/autoscaling.yaml` | Application Auto Scaling: min 1 / desired 1 / max 4, CPU target tracking |
| `stacks/cicd.yaml` | Artifact bucket, CodeDeploy blue/green, CodePipeline (ECR + S3 sources), EventBridge trigger |
| `.githooks/pre-push` | Syncs `stacks/` to S3 before every push (see below) |

## Why child templates need a separate sync step

GitSync watches `root-stack.yaml` for changes and re-deploys the stack when it changes — but
`root-stack.yaml`'s nested stacks reference their children via S3 `TemplateURL`s, not local
paths, and GitSync has no idea the `stacks/` folder exists. A **git pre-push hook**
(`.githooks/pre-push`) syncs `stacks/` to an S3 bucket every time you push, so the
`TemplateURL`s always resolve to the version of each child template you just pushed.

Run once after cloning:

```bash
./setup.sh   # git config core.hooksPath .githooks
```

This requires your own AWS CLI credentials locally (not OIDC — it's a local git hook, not a
CI/CD workflow) with `s3:PutObject`/`s3:DeleteObject` on the templates bucket.

## One-time prerequisites (outside CloudFormation)

These exist before `root-stack.yaml` can be created, since the stack's own creation depends on
them:

1. **S3 templates bucket** — `todo-app-infra-templates-eu-central-1-124355645722` (created,
   versioned, encrypted, public access blocked). Run `./setup.sh`, then push once to populate
   `stacks/` via the pre-push hook.
2. **Git sync deployment role** — `arn:aws:iam::124355645722:role/todo-app-cfn-deployment`
   (created). Trusts `cloudformation.amazonaws.com` and
   `cloudformation.sync.codeconnections.amazonaws.com` (scoped to this account's existing
   CodeConnections GitHub connection), and is permission-scoped to `todo-app-*` resources —
   including RDS Proxy and ElastiCache actions, which this account's other GitSync roles
   (`Synccloudformation`, `photouploader-cfn-deployment`) don't have. Select **Existing IAM
   role** in the console's Git sync stack-creation step and pick this one.
3. **GitHub OIDC provider** — this account already has one
   (`arn:aws:iam::124355645722:oidc-provider/token.actions.githubusercontent.com`), reused via
   the `GitHubOidcProviderArn` parameter rather than created fresh (an account can only have one
   OIDC provider per URL).

## Deploying via CloudFormation Git sync

In the CloudFormation console: **Git sync** → connect this repo via CodeConnections → create a
stack with **Sync from Git**, template path `root-stack.yaml`, and either point it at
`deployment-file.yaml` or let the console generate one from the same parameters. GitSync opens
a pull request for the initial stack creation and for every subsequent template change — merge
it to apply.

**Costs money as soon as it's applied**: RDS (Multi-AZ `db.t3.micro`), RDS Proxy, ElastiCache
(2 nodes), the ALB, 4 VPC interface endpoints, and CodePipeline all bill hourly.

### Two-phase bootstrap (no placeholder image needed)

The ECS service needs a real image already sitting in the `todo-app` ECR repo to reach a
healthy steady state — which can't exist on a repo this same deploy is creating. Rather than
depending on a placeholder image from another project, `root-stack.yaml`'s `DeployCompute`
parameter gates `ComputeStack`/`AutoscalingStack`/`CicdStack` behind a `Condition`:

1. **Phase 1** — `DeployCompute: 'false'` (the checked-in default). Deploys
   network/security/database/cache/ecr/iam only. This creates a real, empty `todo-app` ECR
   repo and nothing ECS-related at all.
2. Build and push a real app image, tagged `:latest`, straight to that now-existing repo —
   manually (`docker build`/`docker push` with your own AWS CLI credentials), since the
   pipeline and its GitHub repo variables don't exist until Phase 2 creates them.
3. **Phase 2** — flip `DeployCompute` to `'true'` in `deployment-file.yaml` and push. GitSync
   creates `ComputeStack`/`AutoscalingStack`/`CicdStack` in one clean `CREATE` —
   `stacks/compute.yaml`'s `AppImageUri` is computed automatically as
   `${EcrStack.Outputs.RepositoryUri}:latest`, so nothing else needs setting.
4. From then on, pushes to `todo-app-code`'s `main` build and deploy normally through
   CodeDeploy blue/green - `build-and-deploy.yml` already hardcodes the deterministic
   resource names this convention produces (`todo-app-task`, `todo-app-cicd-artifacts-<account>`,
   the `todo-app-github-actions` role), so nothing needs copying from stack outputs once
   Phase 2 has completed. `DeployCompute` never needs flipping back to `false`.

Before flipping `DeployCompute` to `true` on a fresh stack, double check
`InitialTaskDefinitionRevision` in `deployment-file.yaml` is still correct — see the comment
next to it, and [the `aws-lab` skill](~/.claude/skills/aws-lab/REFERENCE.md) for why ECS task
definition revision numbers never reset.

## Wiring up the app repo

The `todo-app-code` GitHub Actions workflow assumes `todo-app-github-actions` directly (see
`stacks/iam.yaml`) — no GitHub repo variables to copy over. It re-derives the task definition
live via `aws ecs describe-task-definition` on every deploy (only patching the image field), so
the RDS Proxy endpoint, DB secret ARN, and Redis host/port baked in by `stacks/compute.yaml`
never need to be duplicated into the app repo.

## Tagging

`deployment-file.yaml` sets `tags: {Project: todo-app, ManagedBy: CloudFormation-GitSync}` at
the stack level — CloudFormation propagates these to every resource in the stack that supports
tagging, so this covers the whole stack without per-resource `Tags:` blocks (most resources
also carry an explicit `Project` tag for clarity).

## Architecture diagram

See [`diagrams/architecture.py`](diagrams/architecture.py) (diagram-as-code, using the
`diagrams` Python library) and its rendered [`diagrams/architecture.png`](diagrams/architecture.png).
