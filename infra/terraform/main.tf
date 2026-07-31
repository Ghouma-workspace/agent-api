terraform {
  required_version = ">= 1.7"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.60" }
  }

  backend "s3" {
    bucket         = "ai-api-assistant-tfstate"
    key            = "production/terraform.tfstate"
    region         = "eu-west-3"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project   = "ai-api-assistant"
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}