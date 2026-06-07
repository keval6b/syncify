import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteJob,
  enqueueJob,
  getJobs,
  handleDeleteAccount,
  handleLogout,
} from "@/lib/api/queries.ts";
import { Button } from "@/components/ui/button.tsx";
import { SyncRequest, User } from "@/lib/api/types.ts";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Loader2,
  RefreshCcw,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { relative_time } from "@/lib/utils.ts";
import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import posthog from "posthog-js";

export const Route = createFileRoute("/_authenticated/dashboard")({
  component: Dashboard,
});

function JobStateCell({ job }: { job: SyncRequest }) {
  const wrapper = "inline-flex items-center gap-2";
  const iconClass = "h-4 w-4 shrink-0";
  switch (job.status) {
    case "pending":
      return (
        <span className={`${wrapper} text-muted-foreground`}>
          <Clock className={iconClass} />
          <span>Queued</span>
        </span>
      );
    case "running":
      return (
        <span className={wrapper}>
          <Loader2 className={`${iconClass} animate-spin`} />
          <span>Running</span>
        </span>
      );
    case "completed":
      return (
        <span className={wrapper}>
          <CheckCircle2 className={iconClass} />
          <span>
            {job.completed
              ? `Completed ${relative_time(new Date(job.completed))}`
              : "Completed"}
          </span>
        </span>
      );
    case "failed":
      return (
        <span className={`${wrapper} text-destructive`}>
          <AlertCircle className={iconClass} />
          <span>
            {job.completed
              ? `Failed ${relative_time(new Date(job.completed))}`
              : "Failed"}
          </span>
        </span>
      );
  }
}

function Dashboard() {
  const queryClient = useQueryClient();
  const user: User | undefined = queryClient.getQueryData(["user"]);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [cancellingJobId, setCancellingJobId] = useState<string | null>(null);

  const jobsQuery = useQuery({
    queryKey: ["jobs"],
    queryFn: getJobs,
    refetchInterval: (q) => {
      const jobs = q.state.data ?? [];
      if (
        jobs.some((job) => job.status === "pending" || job.status === "running")
      ) {
        return 3000;
      }
      return 30000;
    },
  });

  const enqueueJobQuery = useQuery({
    queryKey: ["enqueueJob"],
    queryFn: async () => {
      await enqueueJob().catch((reason) => {
        toast(reason.message);
      });
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
      return null;
    },
    retry: false,
    enabled: false,
  });

  const deleteAccountMutation = useMutation({
    mutationFn: handleDeleteAccount,
    onError: (e) => {
      toast(e?.message ?? "Failed to delete account");
    },
  });

  async function handleDelete(jobId: string) {
    setCancellingJobId(jobId);
    await deleteJob(jobId).catch((e) => toast(e.message));
    await queryClient.invalidateQueries({ queryKey: ["jobs"] });
    setCancellingJobId(null);
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center justify-space-between">
        <h1 className="flex-1 text-3xl font-bold">Syncify</h1>
        <div className="flex items-center justify-end gap-x-4 flex-wrap">
          {user && (
            <>
              <Button
                variant="link"
                onClick={() =>
                  window.open(
                    `https://open.spotify.com/user/${user.id}`,
                    "_blank",
                  )
                }
              >
                {user.display_name}
              </Button>
              <Button
                variant="ghost"
                disabled={isLoggingOut}
                onClick={async () => {
                  setIsLoggingOut(true);
                  await handleLogout().catch(() => {
                    toast("Logout failed");
                    setIsLoggingOut(false);
                  });
                  posthog.reset();
                  await queryClient.invalidateQueries({ queryKey: ["user"] });
                }}
              >
                {isLoggingOut && <Loader2 className="h-4 w-4 animate-spin" />}
                Logout
              </Button>
              <Button variant="link" onClick={() => setDeleteDialogOpen(true)}>
                Delete Account
              </Button>
            </>
          )}
        </div>
      </div>
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete account?</DialogTitle>
            <DialogDescription>
              This action is permanent. It will remove your Syncify account and
              all associated data. You will need to log in again to recreate it.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteDialogOpen(false)}
              disabled={deleteAccountMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteAccountMutation.mutate()}
              disabled={deleteAccountMutation.isPending}
            >
              {deleteAccountMutation.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              {deleteAccountMutation.isPending ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <div className="flex flex-wrap items-center justify-end gap-4 mt-8">
        <p className="text-sm">Syncing every 24 hours</p>
        <Button
          disabled={enqueueJobQuery.isFetching}
          onClick={() => enqueueJobQuery.refetch()}
        >
          {enqueueJobQuery.isFetching && (
            <Loader2 className="h-4 w-4 animate-spin" />
          )}
          Enqueue Sync
        </Button>
        <Button
          variant="outline"
          disabled={jobsQuery.isFetching}
          onClick={() => jobsQuery.refetch()}
        >
          <RefreshCcw className={jobsQuery.isFetching ? "animate-spin" : ""} />
          Refresh
        </Button>
      </div>
      <div className="overflow-x-auto">
        <table className="table-auto w-full border-collapse">
          <thead>
            <tr className="border-b">
              <th className="px-4 py-2 text-left">ID</th>
              <th className="px-4 py-2 text-left">Created</th>
              <th className="px-4 py-2 text-left">Song Count</th>
              <th className="px-4 py-2 text-left">State</th>
              <th className="px-4 py-2 text-left">Actions</th>
            </tr>
          </thead>
          <tbody>
            {jobsQuery.data?.map((job) => (
              <tr key={job.id} className="border-b">
                <td className="px-4 py-2">{job.id}</td>
                <td className="px-4 py-2">
                  {relative_time(new Date(job.created))}
                </td>
                <td className="px-4 py-2">{job.song_count}</td>
                <td className="px-4 py-2">
                  <JobStateCell job={job} />
                </td>
                <td className="px-4 py-2">
                  {job.status === "pending" && (
                    <Button
                      variant="outline"
                      disabled={cancellingJobId === job.id}
                      onClick={() => handleDelete(job.id)}
                    >
                      {cancellingJobId === job.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <X />
                      )}
                      Cancel
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
