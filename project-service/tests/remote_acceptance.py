import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

BASE_URL = os.getenv("PROJECT_SERVICE_URL", "http://127.0.0.1:18080").rstrip("/")
COMPOSE_FILE = os.getenv("PROJECT_SERVICE_COMPOSE_FILE", "compose.debug.yaml")
COMPOSE_PROJECT = os.getenv("COMPOSE_PROJECT_NAME", "wkdevops-project-service")


def request(
    path: str,
    *,
    method: str = "GET",
    actor: str = "acceptance-owner",
    idempotency_key: str | None = None,
    body: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    headers = {"X-Actor-Id": actor, "X-Trace-Id": "remote-acceptance-final"}
    data = None
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    operation = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(operation, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def wait_for(path: str, expected: int, attempts: int = 30) -> dict[str, object]:
    for _ in range(attempts):
        try:
            status, body = request(path)
            if status == expected:
                return body
        except (OSError, TimeoutError):
            pass
        time.sleep(1)
    raise AssertionError(f"{path} did not reach HTTP {expected}")


def compose(*arguments: str) -> None:
    subprocess.run(
        ["docker", "compose", "-p", COMPOSE_PROJECT, "-f", COMPOSE_FILE, *arguments], check=True
    )


def verify_database_outage() -> None:
    compose("stop", "db")
    try:
        assert request("/health")[0] == 200
        unavailable = wait_for("/ready", 503)
        assert unavailable == {"status": "unavailable", "checks": {"database": {"status": "fail"}}}
    finally:
        compose("start", "db")
        wait_for("/ready", 200)


def main() -> None:
    wait_for("/health", 200)
    wait_for("/ready", 200)
    key = f"acceptance-{uuid4()}"
    payload = {"name": "Remote Golden Project", "description": "Persistent acceptance"}
    first_status, first = request(
        "/api/v1/projects", method="POST", idempotency_key=key, body=payload
    )
    replay_status, replay = request(
        "/api/v1/projects", method="POST", idempotency_key=key, body=payload
    )
    conflict_status, conflict = request(
        "/api/v1/projects", method="POST", idempotency_key=key, body={"name": "Different"}
    )
    other_status, other = request(
        "/api/v1/projects",
        method="POST",
        actor="acceptance-other",
        idempotency_key=key,
        body={"name": "Different"},
    )
    assert first_status == replay_status == other_status == 201
    assert first["data"]["id"] == replay["data"]["id"]
    assert conflict_status == 409 and conflict["error_code"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert other["data"]["id"] != first["data"]["id"]

    concurrent_key = f"parallel-{uuid4()}"

    def create(_: int) -> str:
        status, response = request(
            "/api/v1/projects",
            method="POST",
            actor="parallel",
            idempotency_key=concurrent_key,
            body={"name": "Parallel"},
        )
        assert status == 201
        return str(response["data"]["id"])

    with ThreadPoolExecutor(max_workers=10) as executor:
        assert len(set(executor.map(create, range(10)))) == 1

    if os.getenv("ACCEPTANCE_MANAGE_COMPOSE") == "1":
        project_id = str(first["data"]["id"])
        compose("restart", "api")
        wait_for("/ready", 200)
        assert request(f"/api/v1/projects/{project_id}")[0] == 200
        compose("up", "-d", "--scale", "api=2", "api")
        wait_for("/ready", 200)
        assert request(f"/api/v1/projects/{project_id}")[0] == 200
        verify_database_outage()

    print(
        json.dumps(
            {
                "status": "passed",
                "persistence_restart_checked": os.getenv("ACCEPTANCE_MANAGE_COMPOSE") == "1",
                "concurrency": 10,
            }
        )
    )


if __name__ == "__main__":
    main()
