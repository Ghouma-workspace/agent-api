output "instance_public_ip" {
  value       = aws_eip.ec2.public_ip
  description = "SSH: ssh ec2-user@<this-ip> | App: http://<this-ip>"
}

output "ssh_command" {
  value = "ssh -i ~/.ssh/id_rsa ec2-user@${aws_eip.ec2.public_ip}"
}

output "app_url" {
  value = "http://${aws_eip.ec2.public_ip}"
}