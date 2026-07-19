"""
Diagram-as-code source for the To-Do App architecture (nested-stack /
CloudFormation Git sync design).
Regenerate with:  python3 -m venv .venv && .venv/bin/pip install diagrams
                   .venv/bin/python3 architecture.py
Requires graphviz (`dot`) to be installed on PATH.
"""
from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import ECS, ElasticContainerServiceService
from diagrams.aws.database import RDS, ElastiCache
from diagrams.aws.devtools import Codedeploy, Codepipeline
from diagrams.aws.general import Client
from diagrams.aws.integration import Eventbridge
from diagrams.aws.management import Cloudformation
from diagrams.aws.network import ALB, InternetGateway, VPC
from diagrams.aws.security import IAM, SecretsManager
from diagrams.aws.storage import S3
from diagrams.onprem.vcs import Github

graph_attr = {
    "fontsize": "20",
    "splines": "ortho",
    "pad": "0.5",
}

with Diagram(
    "To-Do App - AWS Architecture (CloudFormation Git Sync)",
    filename="architecture",
    outformat="png",
    show=False,
    direction="TB",
    graph_attr=graph_attr,
):
    users = Client("Users")

    with Cluster("GitHub"):
        infra_repo = Github("todo-app-infra")
        app_repo = Github("todo-app-code")

    with Cluster("Infra deploy path (no CI - a local git hook)"):
        templates_bucket = S3("Templates bucket\n(stacks/*.yaml)")
        gitsync = Cloudformation(
            "CloudFormation Git Sync\n(root-stack.yaml)\n\n"
            "9 nested stacks:\nnetwork, security, database,\n"
            "cache, ecr, iam, compute,\nautoscaling, cicd"
        )

    github_actions_role = IAM("todo-app-github-actions\n(OIDC, no static keys)")

    with Cluster("AWS Account / Region"):
        igw = InternetGateway("Internet Gateway")

        with Cluster("VPC (10.0.0.0/16) - Multi-AZ"):

            with Cluster("Public Subnets (AZ-a / AZ-b)"):
                alb = ALB("ALB\n(prod :80 + test :8081)")

            with Cluster("Private Subnets - ECS (AZ-a / AZ-b)"):
                ecs_service = ElasticContainerServiceService("ECS Service\n(min 1 / desired 1 / max 4,\nCODE_DEPLOY controller)")
                ecs_task = ECS("Spring Boot task\n(blue/green)")

            with Cluster("VPC Endpoints (no NAT Gateway)"):
                vpce = S3("ECR api/dkr, CloudWatch Logs,\nSecrets Manager (Interface)\n+ S3 (Gateway)")

            with Cluster("Private Subnets - Data (AZ-a / AZ-b)"):
                proxy = RDS("RDS Proxy")
                db = RDS("PostgreSQL\ndb.t3 Multi-AZ")
                secret = SecretsManager("DB credentials")

            with Cluster("Private Subnets - Cache (AZ-a / AZ-b)"):
                redis = ElastiCache("ElastiCache Redis\n(TLS required)")

        with Cluster("CI/CD Pipeline"):
            ecr = ECS("ECR Repository")
            artifact_bucket = S3("Artifact bucket\n(deploy-bundle.zip)")
            eventbridge = Eventbridge("EventBridge Rule\n(ECR :latest PUSH)")
            pipeline = Codepipeline("CodePipeline\n(ECR + S3 sources)")
            codedeploy = Codedeploy("CodeDeploy\n(Blue/Green)")

    # Runtime traffic
    users >> Edge(label="HTTPS") >> igw >> alb
    alb >> Edge(label="container port 8080") >> ecs_service >> ecs_task
    ecs_task >> Edge(label="writes\n(JDBC via proxy)") >> proxy >> db
    proxy >> secret
    ecs_task >> Edge(label="cached reads, TLS\n(30s TTL)") >> redis
    ecs_task >> Edge(style="dashed") >> vpce

    # Infra deploy path: a git hook syncs child templates to S3, GitSync
    # itself only ever tracks root-stack.yaml and applies it directly - no
    # OIDC role, no GitHub Actions workflow involved on this side at all.
    infra_repo >> Edge(label="pre-push hook\n(local AWS creds)") >> templates_bucket
    infra_repo >> Edge(label="push to main\n(GitSync watches this)") >> gitsync
    gitsync >> Edge(label="creates/updates\nevery resource below", style="bold") >> igw
    templates_bucket >> Edge(style="dashed", label="TemplateURL") >> gitsync

    # App CI/CD path: live-taskdef pattern, no repo variables needed
    app_repo >> Edge(label="push to main") >> github_actions_role
    github_actions_role >> Edge(label="build + push :sha") >> ecr
    github_actions_role >> Edge(label="describe live taskdef,\npatch image field only") >> artifact_bucket
    github_actions_role >> Edge(label="push :latest\n(last, deliberately)") >> ecr
    ecr >> Edge(label="image PUSH event") >> eventbridge >> pipeline
    artifact_bucket >> pipeline
    pipeline >> codedeploy
    codedeploy >> Edge(label="blue/green shift\n(prod + test listener)") >> ecs_service
