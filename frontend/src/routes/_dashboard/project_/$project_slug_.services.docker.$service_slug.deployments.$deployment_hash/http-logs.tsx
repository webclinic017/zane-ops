import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_dashboard/project/$project_slug/services/docker/$service_slug/deployments/$deployment_hash/http-logs"
)({
  component: () => (
    <div>
      Hello
      /_dashboard/project/$project_slug/services/docker/$service_slug/deployments/$deployment_hash/http-logs!
    </div>
  )
});
