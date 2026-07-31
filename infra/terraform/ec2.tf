# Free tier: t3.micro, Amazon Linux 2023
data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

resource "aws_key_pair" "deployer" {
  key_name   = "${var.app_name}-key"
  public_key = var.ssh_public_key
}

# Elastic IP so your server's address doesn't change on reboot
resource "aws_eip" "ec2" {
  instance = aws_instance.app.id
  domain   = "vpc"
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = "t3.micro"   # free tier
  key_name               = aws_key_pair.deployer.key_name
  vpc_security_group_ids = [aws_security_group.ec2.id]
  subnet_id              = tolist(data.aws_subnets.default.ids)[0]

  # 30GB is the free tier maximum for EBS
  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true
  }

  # Installs Docker + Docker Compose, clones your repo, starts the stack
  user_data = <<-EOF
    #!/bin/bash
    set -e

    # Install Docker
    dnf update -y
    dnf install -y docker git
    systemctl enable docker
    systemctl start docker

    # Install Docker Compose v2
    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
      -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

    # Install latest buildx
    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -SL https://github.com/docker/buildx/releases/latest/download/buildx-v0.21.0.linux-amd64 \
        -o /usr/local/lib/docker/cli-plugins/docker-buildx
    chmod +x /usr/local/lib/docker/cli-plugins/docker-buildx

    # Add ec2-user to docker group
    usermod -aG docker ec2-user

    # Create app directory
    mkdir -p /opt/app
    chown ec2-user:ec2-user /opt/app

    echo "Bootstrap complete. SSH in and run: cd /opt/app && git clone <your-repo> . && cp .env.example .env && nano .env && docker compose up -d"
  EOF

  tags = {
    Name = var.app_name
  }
}