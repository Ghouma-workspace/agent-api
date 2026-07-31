variable "aws_region" {
  default = "eu-west-3"
}

variable "app_name" {
  default = "ai-api-assistant"
}

variable "your_ip" {
  description = "Your home IP for SSH access — find it at https://whatismyip.com"
}

variable "ssh_public_key" {
  description = "Contents of your ~/.ssh/id_rsa.pub"
}