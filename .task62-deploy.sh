#!/bin/sh
set -eu
version="$1"
base=/project/devops-platform
release="$base/releases/$version"
container=wkDEVOPS-platform-postgres-debug
network=wkDEVOPS

[ -z "$(docker ps -a -q --filter "name=^/${container}$")" ]
[ -z "$(docker network ls -q --filter "name=^${network}$")" ]
install -d -m 0755 "$release" "$base/shared" "$base/shared/postgres" "$base/shared/postgres/data"
install -d -m 0700 "$base/shared/secrets"
umask 077
admin_password="$(openssl rand -hex 32)"
printf 'POSTGRES_USER=wkdevops_admin\nPOSTGRES_PASSWORD=%s\nPOSTGRES_DB=postgres\n' "$admin_password" > "$base/shared/secrets/postgres.env"
printf 'project=%s\nrequirement=%s\ntp=%s\ntd=%s\niam=%s\nworkflow=%s\n' \
  "$(openssl rand -hex 32)" "$(openssl rand -hex 32)" "$(openssl rand -hex 32)" \
  "$(openssl rand -hex 32)" "$(openssl rand -hex 32)" "$(openssl rand -hex 32)" \
  > "$base/shared/secrets/databases.env"
chmod 600 "$base/shared/secrets/postgres.env" "$base/shared/secrets/databases.env"
docker network create --driver bridge --label com.wkdevops.owner=platform --label com.wkdevops.task=62 "$network" >/dev/null
docker run -d --name "$container" --network "$network" --restart unless-stopped \
  --label com.wkdevops.owner=platform --label com.wkdevops.task=62 \
  --env-file "$base/shared/secrets/postgres.env" -p 5433:5432 \
  -v "$base/shared/postgres/data:/var/lib/postgresql/data" postgres:16-alpine >/dev/null
printf '%s\n' "$version" > "$release/RELEASE_VERSION"
