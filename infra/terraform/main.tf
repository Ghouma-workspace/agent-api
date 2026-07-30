# Optional cloud deployment target: ECS Fargate + RDS Postgres + ElastiCache Redis.
# This is a skeleton demonstrating the shape of a production deployment, not a
# turnkey apply-and-go stack — VPC/subnet/secret values are left as variables.

terraform {
  required_version = ">= 1.7"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" { default = "us-east-1" }
variable "vpc_id" {}
variable "subnet_ids" { type = list(string) }
variable "container_image" {}
variable "groq_api_key" { sensitive = true }
variable "jwt_secret_key" { sensitive = true }

resource "aws_ecs_cluster" "main" {
  name = "ai-api-assistant"
}

resource "aws_db_instance" "postgres" {
  identifier             = "ai-api-assistant-db"
  engine                 = "postgres"
  engine_version         = "16"
  instance_class         = "db.t4g.micro"
  allocated_storage      = 20
  db_name                = "ai_assistant"
  username               = "postgres"
  manage_master_user_password = true
  skip_final_snapshot    = true
  vpc_security_group_ids = [aws_security_group.db.id]
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "ai-api-assistant-redis"
  engine               = "redis"
  node_type            = "cache.t4g.micro"
  num_cache_nodes      = 1
  security_group_ids   = [aws_security_group.redis.id]
}

resource "aws_security_group" "db" {
  name_prefix = "ai-api-assistant-db-"
  vpc_id      = var.vpc_id
}

resource "aws_security_group" "redis" {
  name_prefix = "ai-api-assistant-redis-"
  vpc_id      = var.vpc_id
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "ai-api-assistant-backend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"

  container_definitions = jsonencode([
    {
      name  = "backend"
      image = var.container_image
      portMappings = [{ containerPort = 8000 }]
      environment = [
        { name = "DATABASE_URL", value = "postgresql+asyncpg://postgres@${aws_db_instance.postgres.endpoint}/ai_assistant" },
        { name = "REDIS_URL", value = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379/0" },
      ]
      secrets = [
        { name = "GROQ_API_KEY", valueFrom = var.groq_api_key },
        { name = "JWT_SECRET_KEY", valueFrom = var.jwt_secret_key },
      ]
    }
  ])
}

resource "aws_ecs_service" "backend" {
  name            = "ai-api-assistant-backend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    subnets = var.subnet_ids
  }
}

output "cluster_name" {
  value = aws_ecs_cluster.main.name
}
