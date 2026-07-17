"""
Diagram-as-code source for the To-Do App architecture.
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
from diagrams.aws.network import ALB, InternetGateway, PrivateSubnet, PublicSubnet, VPC
from diagrams.aws.security import IAM, IAMRole, SecretsManager
from diagrams.aws.storage import S3

graph_attr = {
    "fontsize": "20",
    "splines": "ortho",
    "pad": "0.5",
}

with Diagram(
    "To-Do App - AWS Architecture",
    filename="architecture",
    outformat="png",
    show=False,
    direction="TB",
    graph_attr=graph_attr,
):
    users = Client("Users")
    developer = Client("Developer\n(git push)")

    with Cluster("GitHub"):
        gha = IAMRole("GitHub Actions\n(OIDC, no static keys)")

    oidc_role = IAM("GitHub OIDC\nDeploy Role")

    with Cluster("AWS Account / Region"):
        igw = InternetGateway("Internet Gateway")

        with Cluster("VPC (10.0.0.0/16) - Multi-AZ"):

            with Cluster("Public Subnets (AZ-a / AZ-b)"):
                alb = ALB("Application\nLoad Balancer")

            with Cluster("Private Subnets - ECS (AZ-a / AZ-b)"):
                ecs_service = ElasticContainerServiceService("ECS Fargate Service\n(min 1 / desired 1 / max 4)")
                ecs_task = ECS("Spring Boot\nTask (blue/green)")

            with Cluster("VPC Endpoints"):
                vpce = S3("ECR / CloudWatch Logs /\nSecrets Manager / S3\n(Interface + Gateway)")

            with Cluster("Private Subnets - Data (AZ-a / AZ-b)"):
                proxy = RDS("RDS Proxy")
                db = RDS("PostgreSQL\ndb.t3 Multi-AZ")
                secret = SecretsManager("DB Credentials")

            with Cluster("Private Subnets - Cache (AZ-a / AZ-b)"):
                redis = ElastiCache("ElastiCache\nRedis")

        with Cluster("CI/CD Pipeline"):
            ecr = ECS("ECR Repository")
            eventbridge = Eventbridge("EventBridge Rule\n(ECR image PUSH)")
            pipeline = Codepipeline("CodePipeline")
            codedeploy = Codedeploy("CodeDeploy\n(Blue/Green)")

    users >> Edge(label="HTTPS") >> igw >> alb
    alb >> Edge(label="container port 8080") >> ecs_service >> ecs_task

    ecs_task >> Edge(label="reads/writes\n(JDBC via proxy)") >> proxy >> db
    proxy >> secret
    ecs_task >> Edge(label="cached reads\n(30s TTL)") >> redis
    ecs_task >> Edge(style="dashed") >> vpce

    developer >> gha
    gha >> Edge(label="AssumeRoleWithWebIdentity") >> oidc_role
    oidc_role >> Edge(label="docker push") >> ecr
    oidc_role >> Edge(label="upload taskdef/appspec", style="dashed") >> pipeline
    ecr >> Edge(label="image PUSH event") >> eventbridge >> pipeline >> codedeploy
    codedeploy >> Edge(label="blue/green shift\n(prod + test listener)") >> ecs_service
