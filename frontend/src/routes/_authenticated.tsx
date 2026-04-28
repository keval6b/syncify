import { createFileRoute, Navigate, Outlet } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ApiError, getUser } from "@/lib/api/queries.ts";
import { LoaderCircle } from "lucide-react";
import {useEffect} from "react";
import posthog from "posthog-js";
import {toast} from "sonner";

export const Route = createFileRoute("/_authenticated")({
  component: RouteComponent,
});

function RouteComponent() {
  const userQuery = useQuery({
    queryKey: ["user"],
    queryFn: getUser,
    retry: false,
    refetchInterval: 60000,
  });

  useEffect(() => {
    if (!userQuery.data?.id) return;
    posthog.identify(userQuery.data.id);
  }, [userQuery.data?.id]);

  useEffect(() => {
    if (!userQuery.isError) return;
    if (userQuery.error instanceof ApiError && userQuery.error.status === 401) {
      toast("Session expired. Please log in again.");
    }
  }, [userQuery.error, userQuery.isError]);

  if (userQuery.isLoading) {
    return (
      <div className="container mx-auto p-4">
        <div className="flex items-center justify-center h-screen">
          <LoaderCircle className="animate-spin" />
        </div>
      </div>
    );
  }

  if (userQuery.isError) {
    return <Navigate to="/" />;
  }

  return <Outlet />;
}
