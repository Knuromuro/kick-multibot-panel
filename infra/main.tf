# Minimal example infrastructure using Terraform
provider "aws" {
  region = var.region
}

resource "aws_db_instance" "db" {
  engine = "postgres"
  instance_class = "db.t3.micro"
  allocated_storage = 20
  username = var.db_user
  password = var.db_pass
  skip_final_snapshot = true
}

resource "aws_elasticache_cluster" "redis" {
  engine = "redis"
  node_type = "cache.t3.micro"
  num_cache_nodes = 1
}

variable "region" {
  default = "us-east-1"
}
variable "db_user" {}
variable "db_pass" {}
