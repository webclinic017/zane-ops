import json
from time import monotonic, sleep
from typing import List, TypedDict

import docker
import docker.errors
import requests
from django.conf import settings
from docker.models.networks import Network
from docker.types import RestartPolicy, EndpointSpec, NetworkAttachmentConfig
from rest_framework import status
from wrapt_timeout_decorator import timeout

from .models import (
    Project,
    Volume,
    DockerRegistryService,
    BaseService,
    PortConfiguration,
    URL,
    ArchivedProject,
    ArchivedDockerService,
    ArchivedURL,
    DockerDeployment,
    HealthCheck,
)
from .utils import (
    strip_slash_if_exists,
    DockerSwarmTask,
    DockerSwarmTaskState,
    format_seconds,
)

docker_client: docker.DockerClient | None = None
DOCKER_HUB_REGISTRY_URL = "registry-1.docker.io/v2"
DEFAULT_TIMEOUT_FOR_DOCKER_EVENTS = 10  # seconds
MAX_SERVICE_RESTART_COUNT = 3


def get_docker_client():
    """
    Get docker client
    """
    global docker_client
    if docker_client is None:
        docker_client = docker.from_env()
    return docker_client


def get_network_resource_name(project_id: str) -> str:
    return f"net-{project_id}"


def get_resource_labels(project_id: str, **kwargs):
    return {"zane-managed": "true", "zane-project": project_id, **kwargs}


class DockerImageResultFromRegistry(TypedDict):
    name: str
    description: str
    is_official: bool
    is_automated: bool


class DockerImageResult(TypedDict):
    full_image: str
    description: str


def search_images_docker_hub(term: str) -> List[DockerImageResult]:
    """
    List all images in registry starting with a certain term.
    """
    client = get_docker_client()
    result: List[DockerImageResultFromRegistry] = client.images.search(
        term=term, limit=30
    )
    images_to_return: List[DockerImageResult] = []

    for image in result:
        api_image_result = {}
        if image["is_official"]:
            api_image_result["full_image"] = f'library/{image["name"]}:latest'
        else:
            api_image_result["full_image"] = f'{image["name"]}:latest'
        api_image_result["description"] = image["description"]
        images_to_return.append(api_image_result)
    return images_to_return


def login_to_docker_registry(
    username: str, password: str, registry_url: str = DOCKER_HUB_REGISTRY_URL
):
    client = get_docker_client()
    client.login(
        username=username, password=password, registry=registry_url, reauth=True
    )


class DockerAuthConfig(TypedDict):
    username: str
    password: str


def check_if_docker_image_exists(
    image: str, credentials: DockerAuthConfig = None
) -> bool:
    client = get_docker_client()
    try:
        client.images.get_registry_data(image, auth_config=credentials)
    except docker.errors.APIError:
        return False
    else:
        return True


def cleanup_docker_service_resources(archived_service: ArchivedDockerService):
    client = get_docker_client()
    service_name = get_docker_service_resource_name(
        archived_service.original_id,
        archived_service.project.original_id,
    )

    try:
        swarm_service = client.services.get(service_name)
    except docker.errors.NotFound:
        # we will assume the service has already been deleted
        pass
    else:
        swarm_service.scale(0)

        @timeout(
            DEFAULT_TIMEOUT_FOR_DOCKER_EVENTS,
            exception_message="Timeout encountered when waiting for service to be down",
        )
        def wait_for_service_to_be_down():
            nonlocal client
            nonlocal swarm_service
            print(f"waiting for service {swarm_service.name=} to be down...")
            task_list = swarm_service.tasks()
            while len(task_list) > 0:
                print(
                    f"service {swarm_service.name=} is not down yet, "
                    + f"retrying in {settings.DEFAULT_HEALTHCHECK_WAIT_INTERVAL} seconds..."
                )
                sleep(settings.DEFAULT_HEALTHCHECK_WAIT_INTERVAL)
                task_list = swarm_service.tasks()
                continue
            print(f"service {swarm_service.name=} is down, YAY !! 🎉")

        wait_for_service_to_be_down()

        print("deleting volume list...")
        docker_volume_list = client.volumes.list(
            filters={
                "label": [
                    f"{key}={value}"
                    for key, value in get_resource_labels(
                        archived_service.project.original_id,
                        parent=archived_service.original_id,
                    ).items()
                ]
            }
        )

        for volume in docker_volume_list:
            volume.remove(force=True)
        print(f"deleted {len(docker_volume_list)} volume(s), YAY !! 🎉")
        swarm_service.remove()
        print(f"removed service.")


def get_proxy_service():
    client = get_docker_client()
    services_list = client.services.list(filters={"label": ["zane.role=proxy"]})

    if len(services_list) == 0:
        raise docker.errors.NotFound("Proxy Service is not up")
    proxy_service = services_list[0]
    return proxy_service


def cleanup_project_resources(archived_project: ArchivedProject):
    """
    Cleanup all resources attached to a project after it has been archived, which means :
    - cleaning up volumes (and deleting them in the DB & docker)
    - cleaning up CRONS
    - cleaning up Workers
    - cleaning up services (and deleting the attached volumes)
    - cleaning up docker networks
    - ... (TODO)

    TODO : we will need to cleanup :
      - services
      - workers &
      - CRONs
      - volumes
    """
    client = get_docker_client()

    try:
        network_associated_to_project = client.networks.get(
            get_network_resource_name(archived_project.original_id)
        )
    except docker.errors.NotFound:
        # We will assume the network has been deleted before
        pass
    else:
        detach_network_from_proxy(network_associated_to_project)

        # Wait for service to finish updating before deleting the network
        @timeout(
            DEFAULT_TIMEOUT_FOR_DOCKER_EVENTS,
            exception_message="Timeout encountered when waiting for service to be updated",
        )
        def wait_for_service_to_update():
            nonlocal client
            proxy_service = get_proxy_service()
            for event in client.events(
                decode=True, filters={"service": proxy_service.id}
            ):
                print(f"⏩ received docker event: {event=}")
                if (
                    event["Type"] == "service"
                    and event.get("Action") == "update"
                    and event.get("Actor", {})
                    .get("Attributes", {})
                    .get("updatestate.new")
                    == "completed"
                ):
                    break

        wait_for_service_to_update()
        network_associated_to_project.remove()


def create_project_resources(project: Project):
    client = get_docker_client()
    network = client.networks.create(
        name=get_network_resource_name(project.id),
        scope="swarm",
        driver="overlay",
        labels=get_resource_labels(project.id),
        attachable=True,
    )
    attach_network_to_proxy(network)


def attach_network_to_proxy(network: Network):
    proxy_service = get_proxy_service()
    service_spec = proxy_service.attrs["Spec"]
    current_networks = service_spec.get("TaskTemplate", {}).get("Networks", [])
    network_ids = set(net["Target"] for net in current_networks)
    network_ids.add(network.id)
    proxy_service.update(networks=list(network_ids))


def detach_network_from_proxy(network: Network):
    proxy_service = get_proxy_service()
    service_spec = proxy_service.attrs["Spec"]
    current_networks = service_spec.get("TaskTemplate", {}).get("Networks", [])
    network_ids = set(net["Target"] for net in current_networks)
    if network.id in network_ids:
        network_ids.remove(network.id)
        proxy_service.update(networks=list(network_ids))


def check_if_port_is_available_on_host(port: int) -> bool:
    client = get_docker_client()
    try:
        client.containers.run(
            image="nginx:alpine",
            ports={"80/tcp": ("0.0.0.0", port)},
            command="echo hello world",
            remove=True,
        )
    except docker.errors.APIError:
        return False
    else:
        return True


def get_volume_resource_name(volume: Volume):
    ts_to_full_number = str(volume.created_at.timestamp()).replace(".", "")
    return f"vol-{volume.id}-{ts_to_full_number}"


def create_docker_volume(volume: Volume, service: BaseService):
    client = get_docker_client()

    client.volumes.create(
        name=get_volume_resource_name(volume),
        driver="local",
        labels=get_resource_labels(service.project.id, parent=service.id),
    )


def get_docker_volume_size(volume: Volume) -> int:
    client = get_docker_client()
    docker_volume_name = get_volume_resource_name(volume)

    result: bytes = client.containers.run(
        image="alpine",
        command="du -sb /data",
        volumes={docker_volume_name: {"bind": "/data", "mode": "ro"}},
        remove=True,
    )
    size_string, _ = result.decode(encoding="utf-8").split("\t")
    return int(size_string)


def get_docker_service_resource_name(service_id: str, project_id: str):
    return f"srv-docker-{project_id}-{service_id}"


def scale_down_docker_service(deployment: DockerDeployment):
    service = deployment.service
    client = get_docker_client()

    swarm_service_list = client.services.list(
        filters={
            "name": get_docker_service_resource_name(
                service_id=service.id,
                project_id=service.project.id,
            )
        }
    )

    if len(swarm_service_list) > 0:
        swarm_service = swarm_service_list[0]
        swarm_service.scale(0)


def create_service_from_docker_registry(deployment: DockerDeployment):
    service = deployment.service
    client = get_docker_client()
    auth_config: DockerAuthConfig | None = None
    if (
        service.docker_credentials_username is not None
        and service.docker_credentials_password is not None
    ):
        auth_config = {
            "username": service.docker_credentials_username,
            "password": service.docker_credentials_password,
        }

    client.images.pull(
        repository=service.image_repository,
        tag=deployment.image_tag,
        auth_config=auth_config,
    )

    exposed_ports: dict[int, int] = {}
    endpoint_spec: EndpointSpec | None = None

    # We don't expose HTTP ports with docker because they will be handled by caddy directly
    http_ports = [80, 443]
    for port in service.ports.all():
        if port.host not in http_ports and port.host is not None:
            exposed_ports[port.host] = port.forwarded

    if len(exposed_ports) > 0:
        endpoint_spec = EndpointSpec(ports=exposed_ports)

    mounts: list[str] = []
    docker_volume_list = client.volumes.list(
        filters={
            "label": [
                f"{key}={value}"
                for key, value in get_resource_labels(
                    service.project.id, parent=service.id
                ).items()
            ]
        }
    )
    access_mode_map = {
        Volume.VolumeMode.READ_WRITE: "rw",
        Volume.VolumeMode.READ_ONLY: "ro",
    }
    for docker_volume, volume in zip(
        docker_volume_list, service.volumes.filter(host_path__isnull=True)
    ):
        mounts.append(
            f"{docker_volume.name}:{volume.container_path}:{access_mode_map[volume.mode]}"
        )
    for volume in service.volumes.filter(host_path__isnull=False):
        mounts.append(
            f"{volume.host_path}:{volume.container_path}:{access_mode_map[volume.mode]}"
        )

    envs: list[str] = [f"{env.key}={env.value}" for env in service.env_variables.all()]

    client.services.create(
        image=f"{service.image_repository}:{deployment.image_tag}",
        name=get_docker_service_resource_name(
            service_id=service.id,
            project_id=service.project.id,
        ),
        mounts=mounts,
        endpoint_spec=endpoint_spec,
        env=envs,
        labels=get_resource_labels(service.project.id, deployment_hash=deployment.hash),
        command=service.command,
        networks=[
            NetworkAttachmentConfig(
                target=get_network_resource_name(service.project.id),
                aliases=[alias for alias in service.network_aliases],
            )
        ],
        restart_policy=RestartPolicy(
            condition="on-failure",
            max_attempts=MAX_SERVICE_RESTART_COUNT,
            delay=5,
        ),
    )


def sort_proxy_routes(routes: list[dict[str, list[dict[str, list[str]]]]]):
    """
    This function implement the same ordering as caddy to pass to the caddy proxy API
    reference: https://caddyserver.com/docs/caddyfile/directives#sorting-algorithm
    This code is adapated from caddy source code : https://github.com/caddyserver/caddy/blob/ddb1d2c2b11b860f1e91b43d830d283d1e1363b2/caddyconfig/httpcaddyfile/directives.go#L495-L513
    """

    def path_specificity(route: dict[str, list[dict[str, list[str]]]]):
        path = route["match"][0]["path"][0]
        # Removing trailing '*' for comparison and determining the "real" length
        normalized_path = path.rstrip("*")
        path_length = len(normalized_path)

        # Using a tuple for comparison: first by the normalized length (longest first),
        # then by whether the original path ends with '*' (no wildcard is more specific),
        # and finally by the original path length in case of identical paths except for the wildcard
        return -path_length, path.endswith("*"), -len(path)

    # Sort the paths based on the specified criteria
    sorted_paths = sorted(routes, key=path_specificity)
    return sorted_paths


def get_caddy_request_for_domain(domain: str):
    return {
        "@id": domain,
        "match": [{"host": [domain]}],
        "handle": [
            {
                "handler": "subroute",
                "routes": [],
            }
        ],
        "terminal": True,
    }


def get_caddy_request_for_deployment_url(
    url: str, service_name: str, forwarded_http_port: int
):

    return {
        "@id": url,
        "match": [{"host": [url]}],
        "handle": [
            {
                "handler": "subroute",
                "routes": [
                    {
                        "handle": [
                            {
                                "handle_response": [
                                    {
                                        "match": {"status_code": [2]},
                                        "routes": [
                                            {
                                                "handle": [
                                                    {
                                                        "handler": "headers",
                                                        "request": {},
                                                    }
                                                ]
                                            }
                                        ],
                                    }
                                ],
                                "handler": "reverse_proxy",
                                "headers": {
                                    "request": {
                                        "set": {
                                            "X-Forwarded-Method": [
                                                "{http.request.method}"
                                            ],
                                            "X-Forwarded-Uri": ["{http.request.uri}"],
                                        }
                                    }
                                },
                                "rewrite": {
                                    "method": "GET",
                                    "uri": "/api/auth/me/with-token",
                                },
                                "upstreams": [
                                    {"dial": settings.ZANE_APP_SERVICE_HOST_FROM_PROXY}
                                ],
                            },
                            {
                                "flush_interval": -1,
                                "handler": "reverse_proxy",
                                "upstreams": [
                                    {"dial": f"{service_name}:{forwarded_http_port}"}
                                ],
                            },
                        ]
                    }
                ],
            }
        ],
        "terminal": True,
    }


def get_caddy_id_for_url(url: URL | ArchivedURL):
    normalized_path = strip_slash_if_exists(
        url.base_path, strip_end=True, strip_start=True
    ).replace("/", "-")

    if len(normalized_path) == 0:
        normalized_path = "*"

    return f"{url.domain}-{normalized_path}"


def get_caddy_request_for_url(
    url: URL, service: DockerRegistryService, http_port: PortConfiguration
):
    service_name = get_docker_service_resource_name(
        service_id=service.id,
        project_id=service.project.id,
    )

    proxy_handlers = []

    if url.strip_prefix:
        proxy_handlers.append(
            {
                "handler": "rewrite",
                "strip_path_prefix": strip_slash_if_exists(
                    url.base_path, strip_end=True, strip_start=False
                ),
            }
        )

    proxy_handlers.append(
        {
            "flush_interval": -1,
            "handler": "reverse_proxy",
            "upstreams": [{"dial": f"{service_name}:{http_port.forwarded}"}],
        }
    )
    return {
        "@id": get_caddy_id_for_url(url),
        "handle": [
            {
                "handler": "subroute",
                "routes": [{"handle": proxy_handlers}],
            }
        ],
        "match": [
            {
                "path": [
                    f"{strip_slash_if_exists(url.base_path, strip_end=True, strip_start=False)}/*"
                ],
            }
        ],
    }


def expose_docker_service_to_http(deployment: DockerDeployment) -> None:
    service = deployment.service
    http_port: PortConfiguration = service.ports.filter(host__isnull=True).first()
    if http_port is None:
        raise Exception(
            f"Cannot expose service `{service.slug}` without a HTTP port exposed."
        )

    for url in service.urls.all():
        response = requests.get(
            f"{settings.CADDY_PROXY_ADMIN_HOST}/id/{url.domain}", timeout=5
        )

        # if the domain doesn't exist we create the config for the domain
        if response.status_code == status.HTTP_404_NOT_FOUND:
            requests.post(
                f"{settings.CADDY_PROXY_ADMIN_HOST}/config/apps/http/servers/zane/routes",
                headers={"content-type": "application/json"},
                json=get_caddy_request_for_domain(url.domain),
                timeout=5,
            )

        # add logger if not exists
        response = requests.get(
            f"{settings.CADDY_PROXY_ADMIN_HOST}/id/zane-server/logs/logger_names/{url.domain}",
            headers={"content-type": "application/json", "accept": "application/json"},
            timeout=5,
        )
        if response.json() is None:
            requests.post(
                f"{settings.CADDY_PROXY_ADMIN_HOST}/id/zane-server/logs/logger_names/{url.domain}",
                data=json.dumps(""),
                headers={
                    "content-type": "application/json",
                    "accept": "application/json",
                },
                timeout=5,
            )

        # now we create the config for the URL
        response = requests.get(
            f"{settings.CADDY_PROXY_ADMIN_HOST}/id/{get_caddy_id_for_url(url)}"
        )
        if response.status_code == status.HTTP_404_NOT_FOUND:
            response = requests.get(
                f"{settings.CADDY_PROXY_ADMIN_HOST}/id/{url.domain}/handle/0/routes"
            )
            routes = response.json()
            routes.append(get_caddy_request_for_url(url, service, http_port))
            routes = sort_proxy_routes(routes)

            requests.patch(
                f"{settings.CADDY_PROXY_ADMIN_HOST}/id/{url.domain}/handle/0/routes",
                headers={"content-type": "application/json"},
                json=routes,
                timeout=5,
            )


def expose_docker_service_deployment_to_http(deployment: DockerDeployment) -> None:
    # add URL conf for deployment
    service = deployment.service
    http_port: PortConfiguration = service.ports.filter(host__isnull=True).first()
    if deployment.url is not None:
        response = requests.get(
            f"{settings.CADDY_PROXY_ADMIN_HOST}/id/{deployment.url}", timeout=5
        )

        # if the domain doesn't exist we create the config for the domain
        if response.status_code == status.HTTP_404_NOT_FOUND:
            requests.post(
                f"{settings.CADDY_PROXY_ADMIN_HOST}/config/apps/http/servers/zane/routes",
                headers={"content-type": "application/json"},
                json=get_caddy_request_for_deployment_url(
                    url=deployment.url,
                    service_name=get_docker_service_resource_name(
                        service_id=deployment.service.id,
                        project_id=deployment.service.project.id,
                    ),
                    forwarded_http_port=http_port.forwarded,
                ),
                timeout=5,
            )

            # add logger if not exists
            response = requests.get(
                f"{settings.CADDY_PROXY_ADMIN_HOST}/id/zane-server/logs/logger_names/{deployment.url}",
                headers={
                    "content-type": "application/json",
                    "accept": "application/json",
                },
                timeout=5,
            )
            if response.json() is None:
                requests.post(
                    f"{settings.CADDY_PROXY_ADMIN_HOST}/id/zane-server/logs/logger_names/{deployment.url}",
                    data=json.dumps(""),
                    headers={
                        "content-type": "application/json",
                        "accept": "application/json",
                    },
                    timeout=5,
                )


def unexpose_docker_service_from_http(service: ArchivedDockerService) -> None:
    for url in service.urls.all():
        # get all the routes of the domain
        response = requests.get(
            f"{settings.CADDY_PROXY_ADMIN_HOST}/id/{url.domain}/handle/0/routes",
            timeout=5,
        )

        if response.status_code != 404:
            current_routes: list[dict[str, dict]] = response.json()
            routes = list(
                filter(
                    lambda route: route.get("@id") != get_caddy_id_for_url(url),
                    current_routes,
                )
            )

            # delete the domain and logger config when there are no routes for the domain anymore
            if len(routes) == 0:
                requests.delete(
                    f"{settings.CADDY_PROXY_ADMIN_HOST}/id/{url.domain}",
                    timeout=5,
                )
                requests.delete(
                    f"{settings.CADDY_PROXY_ADMIN_HOST}/id/zane-server/logs/logger_names/{url.domain}",
                    headers={
                        "content-type": "application/json",
                        "accept": "application/json",
                    },
                    timeout=5,
                )
            else:
                # in the other case, we just delete the caddy config
                requests.delete(
                    f"{settings.CADDY_PROXY_ADMIN_HOST}/id/{get_caddy_id_for_url(url)}",
                    timeout=5,
                )

    for url in service.deployment_urls.all():
        requests.delete(
            f"{settings.CADDY_PROXY_ADMIN_HOST}/id/{url.domain}",
            timeout=5,
        )
        requests.delete(
            f"{settings.CADDY_PROXY_ADMIN_HOST}/id/zane-server/logs/logger_names/{url.domain}",
            headers={
                "content-type": "application/json",
                "accept": "application/json",
            },
            timeout=5,
        )


def get_updated_docker_service_deployment_status(
    deployment: DockerDeployment,
    auth_token: str,
    retry_if_not_healthy=False,
) -> tuple[DockerDeployment.DeploymentStatus, str]:
    client = get_docker_client()

    swarm_service = client.services.get(
        get_docker_service_resource_name(
            deployment.service.id, deployment.service.project.id
        )
    )

    start_time = monotonic()
    healthcheck = deployment.service.healthcheck

    healthcheck_timeout = (
        healthcheck.timeout_seconds
        if healthcheck is not None
        else settings.DEFAULT_HEALTHCHECK_TIMEOUT
    )
    healthcheck_attempts = 0
    deployment_status, deployment_status_reason = (
        DockerDeployment.DeploymentStatus.UNHEALTHY,
        "The service failed to meet the healthcheck requirements when starting the service.",
    )
    while (monotonic() - start_time) < healthcheck_timeout:
        healthcheck_attempts += 1
        task_list = swarm_service.tasks(
            filters={"label": f"deployment_hash={deployment.hash}"}
        )
        healthcheck_time_left = healthcheck_timeout - (monotonic() - start_time)
        if healthcheck_time_left < 1:
            # do not override status reason
            if deployment_status_reason is None:
                raise TimeoutError(
                    "Failed to run the healthcheck because there is no time left,"
                    + " please make sure the healthcheck timeout is large enough"
                )
            break

        sleep_time_available = min(
            float(settings.DEFAULT_HEALTHCHECK_WAIT_INTERVAL),
            healthcheck_time_left - 1,
            healthcheck_time_left,
        )
        # TODO (#67) : send system logs when the state changes
        print(
            f"Healtcheck for {deployment.hash=} | ATTEMPT #{healthcheck_attempts} "
            f"| healthcheck_time_left={format_seconds(healthcheck_time_left)} 💓"
        )

        if len(task_list) == 0:
            if deployment.status in [
                DockerDeployment.DeploymentStatus.HEALTHY,
                DockerDeployment.DeploymentStatus.STARTING,
                DockerDeployment.DeploymentStatus.RESTARTING,
            ]:
                return (
                    DockerDeployment.DeploymentStatus.UNHEALTHY,
                    "An Unknown error occurred, did you manually scale down the service ?",
                )
        else:
            most_recent_swarm_task = DockerSwarmTask.from_dict(
                max(
                    task_list,
                    key=lambda task: task["Version"]["Index"],
                )
            )

            starting_status = deployment.DeploymentStatus.STARTING
            # We set the status to restarting, because we get more than one task for this service when we restart it
            if len(task_list) > 1:
                starting_status = deployment.DeploymentStatus.RESTARTING

            state_matrix = {
                DockerSwarmTaskState.NEW: starting_status,
                DockerSwarmTaskState.PENDING: starting_status,
                DockerSwarmTaskState.ASSIGNED: starting_status,
                DockerSwarmTaskState.ACCEPTED: starting_status,
                DockerSwarmTaskState.READY: starting_status,
                DockerSwarmTaskState.PREPARING: starting_status,
                DockerSwarmTaskState.STARTING: starting_status,
                DockerSwarmTaskState.RUNNING: deployment.DeploymentStatus.HEALTHY,
                DockerSwarmTaskState.COMPLETE: deployment.DeploymentStatus.OFFLINE,
                DockerSwarmTaskState.FAILED: deployment.DeploymentStatus.UNHEALTHY,
                DockerSwarmTaskState.SHUTDOWN: deployment.DeploymentStatus.OFFLINE,
                DockerSwarmTaskState.REJECTED: deployment.DeploymentStatus.UNHEALTHY,
                DockerSwarmTaskState.ORPHANED: deployment.DeploymentStatus.UNHEALTHY,
                DockerSwarmTaskState.REMOVE: deployment.DeploymentStatus.OFFLINE,
            }

            exited_without_error = 0
            deployment_status = state_matrix[most_recent_swarm_task.state]
            deployment_status_reason = (
                most_recent_swarm_task.Status.Err
                if most_recent_swarm_task.Status.Err is not None
                else most_recent_swarm_task.Status.Message
            )

            if most_recent_swarm_task.state == DockerSwarmTaskState.SHUTDOWN:
                status_code = most_recent_swarm_task.Status.ContainerStatus.ExitCode
                if (
                    status_code is not None and status_code != exited_without_error
                ) or most_recent_swarm_task.Status.Err is not None:
                    deployment_status = deployment.DeploymentStatus.UNHEALTHY

            if most_recent_swarm_task.state == DockerSwarmTaskState.RUNNING:
                if healthcheck is not None:

                    @timeout(
                        healthcheck_time_left,
                        exception_message="The service failed to meet the healthcheck in the timeout provided",
                    )
                    def run_healthcheck():
                        nonlocal deployment_status
                        nonlocal deployment_status_reason
                        nonlocal client

                        print(
                            f"Running custom healthcheck {healthcheck.type=} - {healthcheck.value=}"
                        )
                        if healthcheck.type == HealthCheck.HealthCheckType.COMMAND:
                            container = client.containers.get(
                                most_recent_swarm_task.container_id
                            )
                            exit_code, output = container.exec_run(
                                cmd=healthcheck.value,
                                stdout=True,
                                stderr=True,
                                stdin=False,
                            )

                            if exit_code == 0:
                                deployment_status = (
                                    DockerDeployment.DeploymentStatus.HEALTHY
                                )
                            else:
                                deployment_status = (
                                    DockerDeployment.DeploymentStatus.UNHEALTHY
                                )
                            deployment_status_reason = output.decode("utf-8")
                        else:
                            scheme = (
                                "https"
                                if settings.ENVIRONMENT == settings.PRODUCTION_ENV
                                else "http"
                            )
                            full_url = (
                                f"{scheme}://{deployment.url + healthcheck.value}"
                            )
                            response = requests.get(
                                full_url,
                                headers={"Authorization": f"Token {auth_token}"},
                                timeout=min(healthcheck_time_left, 5),
                            )
                            if response.status_code == status.HTTP_200_OK:
                                deployment_status = (
                                    DockerDeployment.DeploymentStatus.HEALTHY
                                )
                            else:
                                deployment_status = (
                                    DockerDeployment.DeploymentStatus.UNHEALTHY
                                )
                            deployment_status_reason = response.content.decode("utf-8")

                    try:
                        run_healthcheck()
                    except TimeoutError as e:
                        deployment_status = deployment.DeploymentStatus.UNHEALTHY
                        deployment_status_reason = str(e)
                        break

            if (
                retry_if_not_healthy
                and deployment_status != DockerDeployment.DeploymentStatus.HEALTHY
            ):
                # TODO (#67) : send system logs when the state changes
                print(
                    f"Healtcheck for deployment {deployment.hash} | ATTEMPT #{healthcheck_attempts} | FAILED,"
                    + f" Retrying in {format_seconds(sleep_time_available)} 🔄"
                )
                sleep(sleep_time_available)
                continue
            # TODO (#67) : send system logs when the state changes

            print(
                f"Healtcheck for {deployment.hash=} | ATTEMPT #{healthcheck_attempts} "
                f"| finished with {deployment_status=} ✅"
            )
            return deployment_status, deployment_status_reason

        sleep(sleep_time_available)
        continue

    return deployment_status, deployment_status_reason
