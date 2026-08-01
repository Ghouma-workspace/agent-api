# Default VPC — free tier accounts already have one, no need to create
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_security_group" "ec2" {
  name_prefix = "${var.app_name}-ec2-"
  vpc_id      = data.aws_vpc.default.id

  # SSH — your IP for manual access + GitHub Actions for CI/CD
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [
      "${var.your_ip}/32",
      "0.0.0.0/0"    # GitHub Actions runners — protected by private key auth
    ]
  }

  # HTTP — public
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTPS — public
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Observability UIs — your IP only (Grafana, Jaeger, Langfuse, Prometheus)
  # ingress {
  #   from_port   = 3000
  #   to_port     = 3001
  #   protocol    = "tcp"
  #   cidr_blocks = ["${var.your_ip}/32"]
  # }

  # ingress {
  #   from_port   = 9090
  #   to_port     = 9090
  #   protocol    = "tcp"
  #   cidr_blocks = ["${var.your_ip}/32"]
  # }

  # ingress {
  #   from_port   = 16686
  #   to_port     = 16686
  #   protocol    = "tcp"
  #   cidr_blocks = ["${var.your_ip}/32"]
  # }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}