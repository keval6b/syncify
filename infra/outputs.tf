output "cloudfront_domain" {
  value = module.frontend.cloudfront_domain
}

output "s3_bucket_name" {
  value = module.frontend.bucket_name
}

output "cloudfront_distribution_id" {
  value = module.frontend.distribution_id
}

output "api_url" {
  value = module.compute.api_url
}
