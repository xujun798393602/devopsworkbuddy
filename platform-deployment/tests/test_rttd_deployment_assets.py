"""Static safety gates for requirement/TP/TD integration assets."""

import json
import re
import shlex
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
WORKSPACE_ROOT = ROOT.parent
WHEELHOUSE = WORKSPACE_ROOT / "wheelhouse" / "linux-x86_64-cp312"
SERVICE_PORTS = {
    "iam-service": "18140",
    "workflow-service": "18150",
    "requirement-service": "18110",
    "tp-service": "18120",
    "td-service": "18130",
    "audit-service": "18160",
    "notification-service": "18170",
}


def test_compose_defines_all_services_with_isolated_runtime_contracts() -> None:
    """Validate the complete seven-service compose runtime contract."""
    document = yaml.safe_load((ROOT / "compose.integration.yaml").read_text(encoding="utf-8"))
    assert document["name"] == "wkdevops-rttd"
    services = document["services"]
    assert set(SERVICE_PORTS) <= set(services)
    database_names: set[str] = set()
    for service_name, port in SERVICE_PORTS.items():
        service = services[service_name]
        assert service["container_name"] == f"wkDEVOPS-{service_name}"
        assert service["user"] == "10001:10001"
        assert any(mapping.endswith(f":{port}") for mapping in service["ports"])
        assert all("18080" not in mapping for mapping in service["ports"])
        assert service["read_only"] is True
        assert "no-new-privileges:true" in service["security_opt"]
        assert service["environment"]["APP_ENV"] in PRODUCTION_SAFE_APP_ENVIRONMENTS
        database_url = service["environment"]["DATABASE_URL"]
        assert database_url == _domain_database_variable(service_name), (
            f"{service_name}: DATABASE_URL must be injected as "
            f"{_domain_database_variable(service_name)}, found {database_url}"
        )
        database_names.add(database_url)
        health_command = " ".join(service["healthcheck"]["test"])
        assert f"127.0.0.1:{port}/ready" in health_command
    assert len(database_names) == len(SERVICE_PORTS)


def test_each_domain_has_a_private_database() -> None:
    sql = (ROOT / "postgres" / "init-databases.sql").read_text(encoding="utf-8")
    for service_name in SERVICE_PORTS:
        database = service_name.removesuffix("-service").replace("-", "_") + "_db"
        assert f"CREATE DATABASE {database};" in sql


def test_trace_projection_queue_is_quorum_and_bound_to_domains() -> None:
    definitions = json.loads((ROOT / "rabbitmq" / "definitions.json").read_text(encoding="utf-8"))
    queue = next(item for item in definitions["queues"] if item["name"] == "tp.trace-projection.v1")
    assert queue["arguments"]["x-queue-type"] == "quorum"
    keys = {
        item["routing_key"]
        for item in definitions["bindings"]
        if item["destination"] == "tp.trace-projection.v1"
    }
    assert keys == {"requirement.#", "tp.#", "td.#"}


def _copy_sources(dockerfile: str) -> list[str]:
    """Return local sources from simple Dockerfile COPY instructions."""
    sources: list[str] = []
    for line in dockerfile.splitlines():
        if not line.lstrip().upper().startswith("COPY "):
            continue
        tokens = shlex.split(line, comments=True)
        if tokens and tokens[0].upper() == "COPY" and len(tokens) >= 3:
            sources.extend(token for token in tokens[1:-1] if not token.startswith("--"))
    return sources


def _normalize(name: str) -> str:
    """Normalize a distribution name per PEP 503 so wheels and requests compare equal."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _wheelhouse_requirements(dockerfile: str) -> list[str]:
    """Return the package names pip is asked to install from the offline wheelhouse."""
    joined = dockerfile.replace("\\\n", " ")
    requirements: list[str] = []
    for line in joined.splitlines():
        for command in line.split("&&"):
            command = command.strip()
            if "--find-links=/wheelhouse" not in command:
                continue
            tokens = shlex.split(command)
            if "install" not in tokens:
                continue
            for token in tokens[tokens.index("install") + 1:]:
                if token.startswith("-") or token == ".":
                    continue
                if token.startswith("$") or "/" in token or token.endswith(".whl"):
                    # A locally built artifact such as "$SERVICE_WHEEL": the wheelhouse only
                    # resolves its dependencies, the artifact itself is never looked up there.
                    continue
                requirements.append(token)
    return requirements


def test_seven_service_dockerfiles_are_offline_non_root_and_observable() -> None:
    for service_name, port in SERVICE_PORTS.items():
        dockerfile = (WORKSPACE_ROOT / service_name / "Dockerfile").read_text(
            encoding="utf-8"
        )
        assert "ARG PYTHON_IMAGE=python:3.12-slim" in dockerfile
        assert "FROM ${PYTHON_IMAGE}" in dockerfile
        assert "--no-index --find-links=/wheelhouse" in dockerfile
        assert "COPY wheelhouse/linux-x86_64-cp312 /wheelhouse" in dockerfile
        assert "python -m pip wheel --no-index --no-deps --no-build-isolation" in dockerfile
        assert (
            'python -m pip install --no-index --find-links=/wheelhouse "$SERVICE_WHEEL"'
            in dockerfile
        )
        assert 'pip install --no-index --no-deps "$SERVICE_WHEEL"' not in dockerfile
        assert "pip install --no-index --no-deps ." not in dockerfile
        assert "adduser" not in dockerfile
        assert "addgroup" not in dockerfile
        assert "wkdevops:wkdevops" not in dockerfile
        assert "ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_INDEX=1 HOME=/tmp" in dockerfile
        assert dockerfile.count("USER 10001:10001") == 1
        assert "HEALTHCHECK" in dockerfile
        assert f"127.0.0.1:{port}/ready" in dockerfile
        assert f"127.0.0.1:{port}/health" not in dockerfile
        assert 'CMD ["gunicorn"' in dockerfile
        for source in _copy_sources(dockerfile):
            assert (WORKSPACE_ROOT / source).exists(), (
                f"{service_name}: missing COPY source {source} in workspace build context"
            )


def test_dockerfile_pip_requirements_are_vendored_in_the_offline_wheelhouse() -> None:
    """Every package installed from the wheelhouse must actually be vendored there.

    Regression guard for the task51 fix4 build failure: the Dockerfiles asked pip for
    ``wheel``, which was never collected into ``wheelhouse/linux-x86_64-cp312``. Under
    ``--no-index`` that is an unrecoverable build error ("No matching distribution found
    for wheel") that only surfaced after a full seven-service ``--no-cache`` build.
    ``setuptools>=70.1`` vendors ``bdist_wheel``, so the external package is unnecessary
    with ``--no-build-isolation``. This closure check fails in milliseconds instead.
    """
    available = {_normalize(path.name.split("-")[0]) for path in WHEELHOUSE.glob("*.whl")}
    assert available, f"offline wheelhouse is empty: {WHEELHOUSE}"
    for service_name in SERVICE_PORTS:
        dockerfile = (WORKSPACE_ROOT / service_name / "Dockerfile").read_text(encoding="utf-8")
        requested = _wheelhouse_requirements(dockerfile)
        assert requested, f"{service_name}: no wheelhouse install detected in Dockerfile"
        for package in requested:
            assert _normalize(package) in available, (
                f"{service_name}: Dockerfile installs '{package}' from the offline "
                f"wheelhouse, but no matching wheel is vendored in {WHEELHOUSE.name}"
            )


def _declared_runtime_dependencies(service_name: str) -> list[str]:
    """Return the PEP 503 normalized runtime dependency names a service declares."""
    document = tomllib.loads(
        (WORKSPACE_ROOT / service_name / "pyproject.toml").read_text(encoding="utf-8")
    )
    names: list[str] = []
    for dependency in document["project"].get("dependencies", []):
        name = re.split(r"[\[<>=!~;\s]", dependency, maxsplit=1)[0]
        if name:
            names.append(_normalize(name))
    return names


def test_service_wheel_install_resolves_its_declared_dependency_closure() -> None:
    """The service wheel must be installed with offline dependency resolution.

    Regression guard for the task51 fix5 build failure: the Dockerfiles installed the
    freshly built service wheel with ``--no-deps`` while the explicit pre-install list
    only covered ``setuptools alembic sqlalchemy psycopg psycopg-binary gunicorn``.
    Runtime requirements such as ``flask``, ``jinja2``, ``pyjwt``, ``argon2-cffi`` and
    ``pyotp`` were therefore never installed, so the in-image ``pip check`` aborted every
    build after the service wheel had already been produced. Resolving the wheel against
    ``--find-links=/wheelhouse`` keeps the build fully offline while guaranteeing the
    declared closure is installed.
    """
    available = {_normalize(path.name.split("-")[0]) for path in WHEELHOUSE.glob("*.whl")}
    assert available, f"offline wheelhouse is empty: {WHEELHOUSE}"
    for service_name in SERVICE_PORTS:
        dockerfile = (WORKSPACE_ROOT / service_name / "Dockerfile").read_text(encoding="utf-8")
        assert 'pip install --no-index --no-deps "$SERVICE_WHEEL"' not in dockerfile, (
            f"{service_name}: the service wheel must not be installed with --no-deps or its "
            "declared runtime dependencies stay missing and the in-image pip check fails"
        )
        assert (
            'pip install --no-index --find-links=/wheelhouse "$SERVICE_WHEEL"' in dockerfile
        ), f"{service_name}: the service wheel must resolve dependencies from the wheelhouse"
        assert "python -m pip check" in dockerfile, (
            f"{service_name}: the image build must verify its own dependency closure"
        )
        declared = _declared_runtime_dependencies(service_name)
        assert declared, f"{service_name}: pyproject declares no runtime dependencies"
        for dependency in declared:
            assert dependency in available, (
                f"{service_name}: declares runtime dependency '{dependency}' that is not "
                f"vendored in {WHEELHOUSE.name}; the offline image build cannot satisfy it"
            )


def test_compose_build_context_contains_every_docker_copy_source() -> None:
    """Prevent Dockerfile string checks from passing with unusable build contexts."""
    document = yaml.safe_load((ROOT / "compose.integration.yaml").read_text(encoding="utf-8"))
    services = document["services"]
    for service_name, port in SERVICE_PORTS.items():
        build = services[service_name]["build"]
        context = (ROOT / build["context"]).resolve()
        assert context == WORKSPACE_ROOT.resolve()
        dockerfile_path = (context / build["dockerfile"]).resolve()
        assert dockerfile_path == (WORKSPACE_ROOT / service_name / "Dockerfile").resolve()
        assert dockerfile_path.is_file()
        dockerfile = dockerfile_path.read_text(encoding="utf-8")
        assert f"EXPOSE {port}" in dockerfile
        assert f"127.0.0.1:{port}/ready" in dockerfile
        for source in _copy_sources(dockerfile):
            assert (context / source).exists(), f"{service_name}: missing COPY source {source}"


def test_seven_service_python_contract_supports_312_and_313() -> None:
    for service_name in SERVICE_PORTS:
        pyproject_path = WORKSPACE_ROOT / service_name / "pyproject.toml"
        document = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        build_system = document["build-system"]
        assert build_system["build-backend"] == "setuptools.build_meta"
        assert build_system["requires"] == ["setuptools>=75"]
        pyproject = document["project"]
        assert pyproject["requires-python"] == ">=3.12,<3.14"
        dependencies = tuple(dependency.lower() for dependency in pyproject["dependencies"])
        for package in ("gunicorn", "sqlalchemy", "psycopg"):
            assert any(dependency.startswith(package) for dependency in dependencies), (
                f"{service_name}: missing production dependency {package}"
            )


def test_mock_capabilities_are_explicit_in_integration_profile() -> None:
    compose = (ROOT / "compose.integration.yaml").read_text(encoding="utf-8")
    assert "AI_ADAPTER: mock" in compose
    assert 'ALLOW_EXPLICIT_MOCK_CAPABILITY: "true"' in compose
    assert "FIX_EVIDENCE_ADAPTER: placeholder" in compose


ALEMBIC_VERSION_NUM_MAX_LENGTH = 32
"""Usable width of the ``alembic_version.version_num`` column.

Alembic provisions its bookkeeping table with a hardcoded
``sa.Column("version_num", sa.String(32))``
(``alembic.runtime.migration.MigrationContext``). A longer revision identifier
therefore aborts ``alembic upgrade head`` with ``StringDataRightTruncation``
at the moment the stamp is written, which makes the limit a hard deployment
contract rather than a naming preference.
"""


def _migration_versions_directory(service_name: str) -> Path:
    """Resolve the alembic ``versions`` directory declared by ``alembic.ini``."""
    service_root = WORKSPACE_ROOT / service_name
    config = (service_root / "alembic.ini").read_text(encoding="utf-8")
    match = re.search(r"^script_location\s*=\s*(.+)$", config, re.MULTILINE)
    assert match is not None, f"{service_name}: alembic.ini declares no script_location"
    location = match.group(1).strip().replace("%(here)s/", "")
    versions = service_root / location / "versions"
    assert versions.is_dir(), f"{service_name}: missing migration directory {versions}"
    return versions


def _revision_graph(service_name: str) -> dict[str, tuple[str | None, str]]:
    """Map every revision identifier to ``(down_revision, module file name)``."""
    graph: dict[str, tuple[str | None, str]] = {}
    for path in sorted(_migration_versions_directory(service_name).glob("*.py")):
        source = path.read_text(encoding="utf-8")
        revision = re.search(
            r"^revision(?:\s*:[^=]+)?\s*=\s*[\"']([^\"']+)[\"']", source, re.MULTILINE
        )
        parent = re.search(
            r"^down_revision(?:\s*:[^=]+)?\s*=\s*(?:[\"']([^\"']+)[\"']|None)",
            source,
            re.MULTILINE,
        )
        assert revision is not None, f"{service_name}: {path.name} declares no revision"
        assert parent is not None, f"{service_name}: {path.name} declares no down_revision"
        identifier = revision.group(1)
        assert identifier not in graph, f"{service_name}: duplicate revision {identifier}"
        graph[identifier] = (parent.group(1), path.name)
    assert graph, f"{service_name}: no alembic revisions found"
    return graph


def test_alembic_revision_identifiers_fit_the_version_table_column() -> None:
    """Reject revisions that ``alembic upgrade head`` is unable to stamp.

    Regression guard for the PG16 migration abort: the 40 character
    ``0002_notification_production_persistence`` identifier raised
    ``value too long for type character varying(32)`` and rolled the whole
    upgrade back after its DDL had already executed.
    """
    oversized: list[str] = []
    for service_name in SERVICE_PORTS:
        for identifier, (_, file_name) in _revision_graph(service_name).items():
            if len(identifier) > ALEMBIC_VERSION_NUM_MAX_LENGTH:
                oversized.append(
                    f"{service_name}/{file_name}: {identifier} ({len(identifier)} chars)"
                )
    assert not oversized, (
        "revision identifiers exceed alembic_version.version_num("
        f"{ALEMBIC_VERSION_NUM_MAX_LENGTH}): " + "; ".join(sorted(oversized))
    )


def test_alembic_revision_graphs_are_single_head_single_root_and_named_consistently() -> None:
    """Every service must expose exactly one resolvable, single-rooted head."""
    for service_name in SERVICE_PORTS:
        graph = _revision_graph(service_name)
        for identifier, (parent, file_name) in graph.items():
            assert Path(file_name).stem == identifier, (
                f"{service_name}: module {file_name} does not match revision {identifier}"
            )
            if parent is not None:
                assert parent in graph, (
                    f"{service_name}: {identifier} points at unknown parent {parent}"
                )
        referenced = {parent for parent, _ in graph.values() if parent is not None}
        heads = sorted(set(graph) - referenced)
        assert len(heads) == 1, f"{service_name}: expected exactly one head, found {heads}"
        roots = sorted(name for name, (parent, _) in graph.items() if parent is None)
        assert len(roots) == 1, f"{service_name}: expected exactly one root, found {roots}"


PRODUCTION_SAFE_APP_ENVIRONMENTS = frozenset({"production", "container"})
"""``APP_ENV`` values that arm every service's ``DATABASE_URL`` fail-fast check.

Each service resolves ``os.getenv("APP_ENV", "development")`` and only raises
``RuntimeError("DATABASE_URL is required in production")`` for these values.
Any other value lets a missing DSN silently select the in-memory repository,
which still answers ``/ready`` with HTTP 200 and therefore fakes a green
deployment.
"""

PROFILE_GATED_INFRASTRUCTURE = ("postgres", "rabbitmq")
"""Compose services that exist purely as disposable local scaffolding."""

PLATFORM_POSTGRES_HOST_PORT = "25432"
"""Loopback port already owned by the managed PostgreSQL 16 platform instance."""

CREDENTIAL_VARIABLE_PATTERN = re.compile(
    r"\$\{([A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|CREDENTIAL)[A-Z0-9_]*):-([^}]*)\}"
)
"""Matches ``${SOME_PASSWORD:-fallback}`` so a literal fallback can be rejected."""

EMBEDDED_CREDENTIAL_PATTERN = re.compile(r"://[^/\s:@]+:[^/\s@]+@")
"""Matches ``scheme://user:secret@host`` credentials inlined into a URL."""


def _domain_database_variable(service_name: str) -> str:
    """Return the dedicated injection variable expected for one domain."""
    domain = service_name.removesuffix("-service").replace("-", "_").upper()
    return "${" + domain + "_DATABASE_URL}"


def _compose_document() -> dict:
    """Parse the integration compose profile."""
    return yaml.safe_load((ROOT / "compose.integration.yaml").read_text(encoding="utf-8"))


def _compose_text() -> str:
    """Return the raw, uninterpolated compose source."""
    return (ROOT / "compose.integration.yaml").read_text(encoding="utf-8")


def test_every_service_arms_its_production_database_guard() -> None:
    """Refuse a profile that leaves the in-memory downgrade path reachable.

    Regression guard: the profile shipped no ``APP_ENV`` at all, so every
    service fell back to ``development`` and would have booted a memory
    repository -- reporting seven healthy containers while writing nothing to
    PostgreSQL -- had any ``*_DATABASE_URL`` been missing.
    """
    services = _compose_document()["services"]
    unguarded = [
        f"{name}: APP_ENV={services[name].get('environment', {}).get('APP_ENV')!r}"
        for name in SERVICE_PORTS
        if services[name].get("environment", {}).get("APP_ENV")
        not in PRODUCTION_SAFE_APP_ENVIRONMENTS
    ]
    assert not unguarded, (
        "services must declare APP_ENV in "
        f"{sorted(PRODUCTION_SAFE_APP_ENVIRONMENTS)}: " + "; ".join(unguarded)
    )


def test_domain_database_urls_are_externally_injected_and_private() -> None:
    """Every domain must read a dedicated, defaulted-free connection variable."""
    services = _compose_document()["services"]
    variables: set[str] = set()
    for service_name in SERVICE_PORTS:
        expected = _domain_database_variable(service_name)
        actual = services[service_name]["environment"]["DATABASE_URL"]
        assert actual == expected, f"{service_name}: expected {expected}, found {actual}"
        variables.add(actual)
    assert len(variables) == len(SERVICE_PORTS), "domains must not share a database URL"


def test_compose_declares_no_plaintext_credential_defaults() -> None:
    """Reject checked-in passwords, whether as a default or inlined in a URL.

    Regression guard: the profile shipped
    ``${POSTGRES_PASSWORD:-wkdevops-integration-only}`` plus seven
    ``postgresql+psycopg://postgres:${POSTGRES_PASSWORD:-...}@postgres/...``
    fallbacks, so a real password lived in the repository and any operator who
    forgot to inject one silently got the published value.
    """
    text = _compose_text()
    literal_defaults = [
        f"${{{match.group(1)}:-{match.group(2)}}}"
        for match in CREDENTIAL_VARIABLE_PATTERN.finditer(text)
        if match.group(2).strip()
    ]
    assert not literal_defaults, (
        "credential variables must not carry a literal default: "
        + "; ".join(sorted(literal_defaults))
    )
    inlined = sorted({match.group(0) for match in EMBEDDED_CREDENTIAL_PATTERN.finditer(text)})
    assert not inlined, "credentials must not be inlined into a URL: " + "; ".join(inlined)


def test_health_probes_exercise_the_readiness_dependency_check() -> None:
    """Container health must reflect the database, not a static literal.

    ``/health`` returns a constant payload without touching any dependency, so
    probing it reports healthy even for a service running entirely in memory.
    ``/ready`` performs the actual connectivity check and answers 503 when the
    private database is unreachable.
    """
    services = _compose_document()["services"]
    for service_name, port in SERVICE_PORTS.items():
        command = " ".join(services[service_name]["healthcheck"]["test"])
        assert f"127.0.0.1:{port}/ready" in command, (
            f"{service_name}: healthcheck must probe /ready, found {command}"
        )
        assert f"{port}/health" not in command, (
            f"{service_name}: healthcheck must not probe the dependency-blind /health"
        )


def test_local_only_infrastructure_is_profile_gated_and_loopback_bound() -> None:
    """Disposable scaffolding must never start, or bind, by accident.

    Regression guard: the bundled postgres defaulted to host port 25432, which
    the managed PostgreSQL 16 instance already owns, so a plain
    ``docker compose up`` aborted with ``port is already allocated``. It also
    published on every interface and pinned a different major version.
    """
    services = _compose_document()["services"]
    for name in PROFILE_GATED_INFRASTRUCTURE:
        service = services[name]
        assert service.get("profiles"), f"{name}: must be gated behind a compose profile"
        for mapping in service.get("ports", []):
            assert mapping.startswith("127.0.0.1:"), (
                f"{name}: {mapping} must publish on loopback only"
            )
            assert f":-{PLATFORM_POSTGRES_HOST_PORT}}}" not in mapping, (
                f"{name}: {mapping} defaults to the port owned by the platform database"
            )


def test_services_never_depend_on_profile_gated_infrastructure() -> None:
    """The seven services must be startable without the disposable scaffolding.

    Compose rejects a profile-less service that declares ``depends_on`` a
    profiled one, and the deployment target is an externally managed database,
    so the dependency must not exist at all.
    """
    services = _compose_document()["services"]
    gated = {name for name in services if services[name].get("profiles")}
    for service_name in SERVICE_PORTS:
        dependencies = set(services[service_name].get("depends_on") or {})
        leaked = sorted(dependencies & gated)
        assert not leaked, f"{service_name}: must not depend on profiled services {leaked}"


def test_services_join_the_external_platform_network() -> None:
    """Services must attach to the pre-existing network hosting the database."""
    document = _compose_document()
    network = document["networks"]["platform"]
    assert network["external"] is True, "the platform network must not be compose-managed"
    assert network["name"] == "wkDEVOPS"
    services = document["services"]
    for service_name in SERVICE_PORTS:
        assert services[service_name]["networks"] == ["platform"], (
            f"{service_name}: must join the external platform network"
        )


def test_iam_acknowledges_its_development_login_downgrade() -> None:
    """Arming ``APP_ENV=container`` must not leave IAM unable to boot.

    Regression guard for the task51 fix8 start-up abort: IAM rejects every
    production-like profile while the local development authentication
    provider is active, and that provider defaults to enabled. Declaring
    ``APP_ENV: container`` without stating the downgrade therefore turned the
    very first ``docker compose up`` into a crash loop that no externally
    injectable variable could have prevented, because ``jwt_provider`` and
    ``break_glass_enabled`` were not readable from the environment at all.
    The profile must name the downgrade explicitly, exactly as tp-service
    names its mock AI adapter.
    """
    services = _compose_document()["services"]
    environment = services["iam-service"]["environment"]
    assert environment.get("ALLOW_EXPLICIT_DEV_AUTH") == "true", (
        "iam-service authenticates through the local development provider in "
        "the integration profile and must acknowledge that downgrade explicitly"
    )
    leaked = sorted(
        name
        for name in SERVICE_PORTS
        if name != "iam-service"
        and "ALLOW_EXPLICIT_DEV_AUTH" in (services[name].get("environment") or {})
    )
    assert not leaked, f"only iam-service owns a login provider, found also on {leaked}"
