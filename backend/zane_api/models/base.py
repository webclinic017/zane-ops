import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_celery_beat.models import PeriodicTask, IntervalSchedule, CrontabSchedule
from shortuuid.django_fields import ShortUUIDField

from ..utils import strip_slash_if_exists, datetime_to_timestamp_string
from ..validators import validate_url_domain, validate_url_path


class TimestampedModel(models.Model):
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class Project(TimestampedModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    slug = models.SlugField(max_length=255, unique=True)
    id = ShortUUIDField(
        length=11,
        max_length=255,
        primary_key=True,
        prefix="prj_",
    )
    description = models.TextField(blank=True, null=True)

    @property
    def create_task_id(self):
        return f"create-{self.id}-{datetime_to_timestamp_string(self.created_at)}"

    @property
    def archive_task_id(self):
        return f"archive-{self.id}-{datetime_to_timestamp_string(self.updated_at)}"

    def __str__(self):
        return f"Project({self.slug})"

    class Meta:
        ordering = ["-updated_at"]


class URL(models.Model):
    domain = models.CharField(
        max_length=1000, null=True, blank=True, validators=[validate_url_domain]
    )
    base_path = models.CharField(default="/", validators=[validate_url_path])
    strip_prefix = models.BooleanField(default=True)

    def __str__(self):
        base_path = (
            "/"
            if self.base_path == "/"
            else strip_slash_if_exists(
                self.base_path, strip_start=False, strip_end=True
            )
        )
        return f'URL(domain="{self.domain}"), base_path="{base_path}")'

    class Meta:
        unique_together = (
            "domain",
            "base_path",
        )


class HealthCheck(models.Model):
    class HealthCheckType(models.TextChoices):
        COMMAND = "COMMAND", _("Command")
        PATH = "PATH", _("Path")

    type = models.CharField(
        max_length=255,
        null=False,
        choices=HealthCheckType.choices,
        default=HealthCheckType.PATH,
    )
    value = models.CharField(max_length=255, null=False, default="/")
    interval_seconds = models.PositiveIntegerField(default=15)
    timeout_seconds = models.PositiveIntegerField(default=60)


class BaseService(TimestampedModel):
    slug = models.SlugField(max_length=255)
    project = models.ForeignKey(to=Project, on_delete=models.CASCADE)
    volumes = models.ManyToManyField(to="Volume")
    ports = models.ManyToManyField(to="PortConfiguration")
    urls = models.ManyToManyField(to=URL)
    healthcheck = models.ForeignKey(
        to=HealthCheck, null=True, on_delete=models.SET_NULL
    )
    network_alias = models.CharField(max_length=300, null=True, unique=True)

    class Meta:
        abstract = True
        unique_together = (
            "slug",
            "project",
        )

    def delete_resources(self):
        self.ports.filter().delete()
        self.urls.filter().delete()
        self.volumes.filter().delete()
        if self.healthcheck is not None:
            self.healthcheck.delete()


class PortConfiguration(models.Model):
    host = models.PositiveIntegerField(null=True, unique=True)
    forwarded = models.PositiveIntegerField()

    def __str__(self):
        host_port = 80 if self.host is None else self.host
        return f"PortConfiguration({host_port} -> {self.forwarded})"


class BaseEnvVariable(models.Model):
    key = models.CharField(max_length=255)
    value = models.CharField(max_length=255)

    class Meta:
        abstract = True


class DockerEnvVariable(BaseEnvVariable):
    service = models.ForeignKey(
        to="DockerRegistryService",
        on_delete=models.CASCADE,
        related_name="env_variables",
    )

    def __str__(self):
        return f"DockerEnvVariable({self.key})"


class DockerRegistryService(BaseService):
    image_repository = models.CharField(max_length=510, null=False, blank=False)
    command = models.TextField(null=True, blank=True)
    docker_credentials_username = models.CharField(
        max_length=255, null=True, blank=True
    )
    docker_credentials_password = models.CharField(
        max_length=255, null=True, blank=True
    )
    id = ShortUUIDField(
        length=11,
        max_length=255,
        primary_key=True,
        prefix="srv_dkr_",
    )

    def __str__(self):
        return f"DockerRegistryService({self.slug})"

    @property
    def unprefixed_id(self):
        return self.id.replace("srv_dkr_", "") if self.id is not None else None

    @property
    def network_aliases(self):
        return (
            [
                f"{self.network_alias}.{settings.ZANE_PRIVATE_DOMAIN}",
                self.network_alias,
            ]
            if self.network_alias is not None
            else []
        )

    @property
    def archive_task_id(self):
        return f"archive-{self.id}-{datetime_to_timestamp_string(self.updated_at)}"

    def delete_resources(self):
        super().delete_resources()
        all_deployments = self.deployments.all()
        all_monitor_tasks = PeriodicTask.objects.filter(
            dockerdeployment__in=all_deployments
        )

        interval_ids = []
        for task in all_monitor_tasks.all():
            interval_ids.append(task.interval_id)
        IntervalSchedule.objects.filter(id__in=interval_ids).delete()
        all_monitor_tasks.delete()

    def get_latest_deployment(self) -> "DockerDeployment":
        return (
            self.deployments.filter(is_current_production=True)
            .select_related("service", "service__project")
            .prefetch_related(
                "service__volumes",
                "service__urls",
                "service__ports",
                "service__env_variables",
            )
            .order_by("-created_at")
            .first()
        )


class GitRepositoryService(BaseService):
    previews_enabled = models.BooleanField(default=True)
    auto_deploy = models.BooleanField(default=True)
    preview_protected = models.BooleanField(default=True)
    delete_preview_after_merge = models.BooleanField(default=True)
    production_branch_name = models.CharField(max_length=255)
    repository_url = models.URLField(max_length=1000)
    build_success_webhook_url = models.URLField(null=True, blank=True)

    # for docker build context
    dockerfile_path = models.CharField(max_length=255, default="./Dockerfile")
    docker_build_context_dir = models.CharField(max_length=255, default=".")
    docker_cmd = models.CharField(max_length=255, null=True, blank=True)
    id = ShortUUIDField(
        length=11,
        max_length=255,
        primary_key=True,
        prefix="srv_git_",
    )


class GitEnvVariable(BaseEnvVariable):
    service = models.ForeignKey(
        to="GitRepositoryService",
        on_delete=models.CASCADE,
        related_name="env_variables",
    )

    def __str__(self):
        return f"GitEnvVariable({self.key})"


class Volume(TimestampedModel):
    class VolumeMode(models.TextChoices):
        READ_ONLY = "READ_ONLY", _("Read-Only")
        READ_WRITE = "READ_WRITE", _("Read-Write")

    mode = models.CharField(
        max_length=255,
        null=False,
        choices=VolumeMode.choices,
        default=VolumeMode.READ_WRITE,
    )
    name = models.CharField(max_length=255)
    container_path = models.CharField(max_length=255)
    host_path = models.CharField(
        max_length=255, null=True, validators=[validate_url_path]
    )
    id = ShortUUIDField(length=11, max_length=255, primary_key=True, prefix="vol_")

    def __str__(self):
        return f"Volume({self.name})"

    class Meta:
        indexes = [models.Index(fields=["host_path"])]


class BaseDeployment(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)

    logs = models.ManyToManyField(to="SimpleLog")
    http_logs = models.ManyToManyField(to="HttpLog")
    url = models.URLField(null=True)

    class Meta:
        abstract = True


class DockerDeployment(BaseDeployment):
    is_redeploy_of = models.ForeignKey("self", on_delete=models.SET_NULL, null=True)

    class DeploymentStatus(models.TextChoices):
        QUEUED = "QUEUED", _("Queued")
        CANCELLED = "CANCELLED", _("Cancelled")
        FAILED = "FAILED", _("Failed")
        PREPARING = "PREPARING", _("Preparing")
        STARTING = "STARTING", _("Starting")
        RESTARTING = "RESTARTING", _("Restarting")
        HEALTHY = "HEALTHY", _("Healthy")
        UNHEALTHY = "UNHEALTHY", _("Unhealthy")
        OFFLINE = "OFFLINE", _("Offline")

    class DeploymentSlot(models.TextChoices):
        BLUE = "BLUE", _("Blue")
        GREEN = "GREEN", _("Green")

    slot = models.CharField(
        max_length=10,
        choices=DeploymentSlot.choices,
        default=DeploymentSlot.BLUE,
    )

    status = models.CharField(
        max_length=10,
        choices=DeploymentStatus.choices,
        default=DeploymentStatus.QUEUED,
    )
    status_reason = models.TextField(null=True, blank=True)
    is_current_production = models.BooleanField(default=True)
    service = models.ForeignKey(
        to=DockerRegistryService, on_delete=models.CASCADE, related_name="deployments"
    )
    hash = ShortUUIDField(length=11, max_length=255, unique=True, prefix="dpl_dkr_")
    image_tag = models.CharField(max_length=255, default="latest")
    monitor_task = models.ForeignKey(
        to=PeriodicTask, null=True, on_delete=models.SET_NULL
    )

    @property
    def task_id(self):
        return f"deploy-{self.hash}-{self.service.id}-{self.service.project.id}"

    @property
    def unprefixed_hash(self):
        return None if self.hash is None else self.hash.replace("dpl_dkr_", "")

    @property
    def network_aliases(self):
        aliases = []
        if self.service is not None and len(self.service.network_aliases) > 0:
            aliases = self.service.network_aliases + [
                f"{self.service.network_alias}.{self.slot.lower()}.{settings.ZANE_PRIVATE_DOMAIN}",
            ]
        return aliases

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["is_current_production"]),
        ]


class GitDeployment(BaseDeployment):
    is_redeploy_of = models.ForeignKey("self", on_delete=models.SET_NULL, null=True)

    class BuildStatus(models.TextChoices):
        ERROR = "ERROR", _("Error")
        SUCCESS = "SUCCESS", _("Success")
        PENDING = "PENDING", _("Pending")
        QUEUED = "QUEUED", _("Queued")

    build_status = models.CharField(
        max_length=10,
        choices=BuildStatus.choices,
        default=BuildStatus.QUEUED,
    )

    class DeploymentStatus(models.TextChoices):
        QUEUED = "QUEUED", _("Queued")
        PREPARING = "PREPARING", _("Preparing")
        FAILED = "FAILED", _("Failed")
        STARTING = "STARTING", _("Starting")
        RESTARTING = "RESTARTING", _("Restarting")
        BUILDING = "BUILDING", _("Building")
        CANCELLED = "CANCELLED", _("Cancelled")
        HEALTHY = "HEALTHY", _("Healthy")
        UNHEALTHY = "UNHEALTHY", _("UnHealthy")
        OFFLINE = "OFFLINE", _("Offline")
        SLEEPING = "SLEEPING", _("Sleeping")  # preview deploys

    status = models.CharField(
        max_length=10,
        choices=DeploymentStatus.choices,
        default=DeploymentStatus.QUEUED,
    )
    status_reason = models.CharField(max_length=255, null=True)

    class DeploymentEnvironment(models.TextChoices):
        PRODUCTION = "PRODUCTION", _("Production")
        PREVIEW = "PREVIEW", _("Preview")

    deployment_environment = models.CharField(
        max_length=10,
        choices=DeploymentEnvironment.choices,
        default=DeploymentEnvironment.PREVIEW,
    )
    is_current_production = models.BooleanField(default=False)

    commit_hash = models.CharField(
        max_length=40
    )  # Typical length of a Git commit hash, but we will use the short version
    commit_message = models.TextField(blank=True)
    build_duration_in_ms = models.PositiveIntegerField(null=True)
    branch = models.CharField(max_length=255)
    service = models.ForeignKey(to=GitRepositoryService, on_delete=models.CASCADE)
    commit_author_username = models.CharField(max_length=255)
    commit_author_avatar_url = models.URLField(null=True)
    hash = ShortUUIDField(length=11, max_length=255, unique=True, prefix="dpl_git_")

    # @property
    # def image_tags(self) -> List[str]:
    #     tags = []  # type: List[str]
    #     if self.is_current_production:
    #         tags.append("latest")
    #     tags.append(f"{self.branch}-{self.commit_hash}")
    #     return list(map(tags, lambda tag: f"{self.image_name}:{tag}"))
    #
    # @property
    # def image_name(self):
    #     project_prefix = self.service.project.slug
    #     service_prefix = self.service.slug
    #     return f"{project_prefix}-{service_prefix}"

    # @property
    # def domain(self):
    #     if self.is_production:
    #         return self.service.base_domain
    #
    #     return f"{self.service.project.slug}-{self.service.slug}-{self.commit_hash}.{self.service.base_domain}"

    def __str__(self):
        return f"{self.branch} - {self.commit_hash[:7]} - {self.build_status}"

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["is_current_production"]),
        ]


class Log(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class SimpleLog(Log):
    class LogType(models.TextChoices):
        ERROR = "ERROR", _("Error")
        INFO = "INFO", _("Info")

    content = models.TextField(blank=True)
    log_type = models.CharField(
        max_length=10,
        choices=LogType.choices,
        default=LogType.INFO,
    )


class HttpLog(Log):
    class RequestMethod(models.TextChoices):
        GET = "GET", _("GET")
        POST = "POST", _("POST")
        PUT = "PUT", _("PUT")
        DELETE = "DELETE", _("DELETE")
        PATCH = "PATCH", _("PATCH")
        OPTIONS = "OPTIONS", _("OPTIONS")
        HEAD = "HEAD", _("HEAD")

    request_method = models.CharField(
        max_length=7,
        choices=RequestMethod.choices,
    )
    status = models.PositiveIntegerField()
    request_duration_ms = models.PositiveIntegerField()
    request_domain = models.URLField(max_length=1000)
    request_headers = models.JSONField()
    response_headers = models.JSONField()
    ip = models.GenericIPAddressField()
    path = models.CharField(max_length=2000)


class CRON(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=255)
    schedule = models.ForeignKey(to=CrontabSchedule, on_delete=models.RESTRICT)
    archived = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class HttpCRON(CRON):
    class RequestMethod(models.TextChoices):
        GET = "GET", _("GET")
        POST = "POST", _("POST")
        PUT = "PUT", _("PUT")
        DELETE = "DELETE", _("DELETE")
        PATCH = "PATCH", _("PATCH")
        OPTIONS = "OPTIONS", _("OPTIONS")
        HEAD = "HEAD", _("HEAD")

    url = models.URLField(max_length=2000)
    headers = models.JSONField()
    body = models.JSONField()
    method = models.CharField(
        max_length=7,
        choices=RequestMethod.choices,
    )

    def __str__(self):
        return f"HTTP CRON {self.name}"


class ServiceCommandCRON(CRON):
    command = models.TextField()
    dockerService = models.ForeignKey(
        to=DockerRegistryService, null=True, on_delete=models.CASCADE
    )
    gitService = models.ForeignKey(
        to=GitRepositoryService, null=True, on_delete=models.CASCADE
    )

    def __str__(self):
        return f"HTTP CRON {self.name}"
