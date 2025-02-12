import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpIcon,
  ChevronRight,
  Container,
  KeyRound,
  LoaderIcon,
  Rocket,
  Settings,
  TriangleAlert
} from "lucide-react";
import {
  Link,
  Outlet,
  useFetcher,
  useLocation,
  useNavigate
} from "react-router";
import { StatusBadge } from "~/components/status-badge";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator
} from "~/components/ui/breadcrumb";
import { Button, SubmitButton } from "~/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from "~/components/ui/popover";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "~/components/ui/tabs";
import { type DockerService, serviceQueries } from "~/lib/queries";
import type { ValueOf } from "~/lib/types";
import { isNotFoundError, notFound } from "~/lib/utils";
import { cn } from "~/lib/utils";
import { queryClient } from "~/root";
import { formatURL, metaTitle, pluralize } from "~/utils";
import { type Route } from "./+types/service-layout";

export function meta({ params, error }: Route.MetaArgs) {
  const title = !error
    ? params.serviceSlug
    : isNotFoundError(error)
      ? "Error 404 - Service does not exist"
      : "Oops";
  return [metaTitle(title)] satisfies ReturnType<Route.MetaFunction>;
}

export async function clientLoader({ params }: Route.ClientLoaderArgs) {
  let service = await queryClient.ensureQueryData(
    serviceQueries.single({
      project_slug: params.projectSlug,
      service_slug: params.serviceSlug
    })
  );

  if (!service) {
    throw notFound();
  }

  return { service };
}

const TABS = {
  DEPLOYMENTS: "deployments",
  ENV_VARIABLES: "envVariables",
  SETTINGS: "settings"
} as const;

export default function ServiceDetailsLayout({
  loaderData,
  params: { projectSlug: project_slug, serviceSlug: service_slug }
}: Route.ComponentProps) {
  const location = useLocation();
  const navigate = useNavigate();

  const { data: service } = useQuery({
    ...serviceQueries.single({
      project_slug,
      service_slug
    }),
    initialData: loaderData.service
  });

  let currentSelectedTab: ValueOf<typeof TABS> = TABS.DEPLOYMENTS;
  if (location.pathname.match(/env\-variables\/?$/)) {
    currentSelectedTab = TABS.ENV_VARIABLES;
  } else if (location.pathname.match(/settings\/?$/)) {
    currentSelectedTab = TABS.SETTINGS;
  }

  let serviceImage =
    service.image ??
    (
      service.unapplied_changes.filter((change) => change.field === "source")[0]
        ?.new_value as Pick<DockerService, "image" | "credentials">
    )?.image;

  if (serviceImage && !serviceImage.includes(":")) {
    serviceImage += ":latest";
  }
  let extraServiceUrls: DockerService["urls"] = [];

  if (service && service.urls.length > 1) {
    let [_, ...rest] = service.urls;
    extraServiceUrls = rest;
  }

  return (
    <>
      <Breadcrumb>
        <BreadcrumbList className="text-sm">
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to="/">Projects</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={`/project/${project_slug}/`}>{project_slug}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>

          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{service_slug}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <>
        <section
          id="header"
          className="flex flex-col md:flex-row md:items-center gap-4 justify-between"
        >
          <div className="mt-10">
            <h1 className="text-2xl">{service.slug}</h1>
            <p className="flex gap-1 items-center">
              <Container size={15} />
              <span className="text-grey text-sm">{serviceImage}</span>
            </p>
            {service.urls.length > 0 && (
              <div className="flex gap-3 items-center flex-wrap">
                <a
                  href={formatURL(service.urls[0])}
                  target="_blank"
                  className="underline text-link text-sm break-all"
                >
                  {formatURL(service.urls[0])}
                </a>
                {extraServiceUrls.length > 0 && (
                  <Popover>
                    <PopoverTrigger asChild>
                      <button>
                        <StatusBadge
                          className="relative top-0.5 text-xs pl-3 pr-2 inline-flex items-center gap-1"
                          color="gray"
                          pingState="hidden"
                        >
                          <span>
                            {`+${service.urls.length - 1} ${pluralize("url", service.urls.length - 1)}`}
                          </span>
                          <ChevronRight size={15} className="flex-none" />
                        </StatusBadge>
                      </button>
                    </PopoverTrigger>
                    <PopoverContent
                      align="start"
                      side="top"
                      className="px-4 pt-3 pb-2 max-w-[300px] md:max-w-[500px] lg:max-w-[600px] w-auto"
                    >
                      <ul className="w-full">
                        {extraServiceUrls.map((url) => (
                          <li key={url.id} className="w-full">
                            <a
                              href={formatURL(url)}
                              target="_blank"
                              className="underline text-link text-sm inline-block w-full"
                            >
                              <p className="whitespace-nowrap overflow-x-hidden text-ellipsis">
                                {formatURL(url)}
                              </p>
                            </a>
                          </li>
                        ))}
                      </ul>
                    </PopoverContent>
                  </Popover>
                )}
              </div>
            )}
          </div>

          <DeployServiceForm service={service} />
        </section>

        {currentSelectedTab === TABS.SETTINGS && (
          <Button
            variant="outline"
            className={cn(
              "inline-flex gap-2 fixed bottom-10 right-5 md:right-10 z-30",
              "bg-grey text-white dark:text-black"
            )}
            onClick={() => {
              const main = document.querySelector("main");
              main?.scrollIntoView({
                behavior: "smooth",
                block: "start"
              });
            }}
          >
            <span>Back to top</span> <ArrowUpIcon size={15} />
          </Button>
        )}

        <Tabs
          value={currentSelectedTab}
          className="w-full mt-5"
          onValueChange={(value) => {
            switch (value) {
              case TABS.DEPLOYMENTS:
                navigate(".");
                break;
              case TABS.ENV_VARIABLES:
                navigate(`./env-variables`);
                break;
              case TABS.SETTINGS:
                navigate(`./settings`);
                break;
              default:
                break;
            }
          }}
        >
          <TabsList className="overflow-x-auto overflow-y-clip h-[2.55rem] w-full items-start justify-start bg-background rounded-none border-b border-border">
            <TabsTrigger
              value={TABS.DEPLOYMENTS}
              className="flex gap-2 items-center"
            >
              <span>Deployments</span>
              <Rocket size={15} className="flex-none" />
            </TabsTrigger>

            <TabsTrigger
              value={TABS.ENV_VARIABLES}
              className="flex gap-2 items-center"
            >
              <span>Env Variables</span>
              <KeyRound size={15} className="flex-none" />
            </TabsTrigger>

            <TabsTrigger
              value={TABS.SETTINGS}
              className="flex gap-2 items-center"
            >
              <span>Settings</span>
              <Settings size={15} className="flex-none" />
            </TabsTrigger>
          </TabsList>

          <TabsContent value={TABS.DEPLOYMENTS}>
            <Outlet />
          </TabsContent>

          <TabsContent value={TABS.ENV_VARIABLES}>
            <Outlet />
          </TabsContent>
          <TabsContent value={TABS.SETTINGS}>
            <Outlet />
          </TabsContent>
        </Tabs>
      </>
    </>
  );
}

type DeployServiceFormProps = {
  className?: string;
  service: Route.ComponentProps["loaderData"]["service"];
};

function DeployServiceForm({ className, service }: DeployServiceFormProps) {
  const fetcher = useFetcher();
  const isDeploying = fetcher.state !== "idle";

  return (
    <div className={cn("flex items-center gap-2 flex-wrap", className)}>
      {service.unapplied_changes.length > 0 && (
        <Button variant="warning" className="flex-1 md:flex-auto">
          <TriangleAlert size={15} />
          <span className="mx-1">
            {service.unapplied_changes.length}&nbsp;
            {pluralize("unapplied change", service.unapplied_changes.length)}
          </span>
        </Button>
      )}

      <fetcher.Form
        method="post"
        action="./deploy-service"
        className="flex flex-1 md:flex-auto"
      >
        <SubmitButton
          isPending={isDeploying}
          variant="secondary"
          className="w-full"
        >
          {isDeploying ? (
            <>
              <span>Deploying</span>
              <LoaderIcon className="animate-spin" size={15} />
            </>
          ) : (
            "Deploy now"
          )}
        </SubmitButton>
      </fetcher.Form>
    </div>
  );
}
