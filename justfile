default:
    @just --list

# Deploy the current working tree to the staging stack (infra + frontend).
deploy-stg:
    ./scripts/deploy-stg.sh
