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
import { User } from "@/lib/api/types.ts";
import { RefreshCcw, X } from "lucide-react";
import { toast } from "sonner";
import { Progress } from "@/components/ui/progress.tsx";
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

function Dashboard() {
  const queryClient = useQueryClient();
  const user: User | undefined = queryClient.getQueryData(["user"]);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const jobsQuery = useQuery({
    queryKey: ["jobs"],
    queryFn: getJobs,
    refetchInterval: (q) => {
      const jobs = q.state.data ?? [];
      if (jobs.some((job) => !job.completed)) {
        return 1000;
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
    await deleteJob(jobId).catch((e) => toast(e.message));
    await queryClient.invalidateQueries({ queryKey: ["jobs"] });
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
                onClick={async () => {
                  await handleLogout().catch(() => {
                    toast("Logout failed");
                  });
                  posthog.reset();
                  await queryClient.invalidateQueries({ queryKey: ["user"] });
                }}
              >
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
              {deleteAccountMutation.isPending ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <div className="flex flex-wrap items-center justify-end gap-4 mt-8">
        <p className="text-sm">Syncing every 24 hours</p>
        <Button onClick={() => enqueueJobQuery.refetch()}>Enqueue Sync</Button>
        <Button
          variant="outline"
          disabled={jobsQuery.isFetching}
          onClick={() => jobsQuery.refetch()}
        >
          <RefreshCcw /> Refresh
        </Button>
      </div>
      <div className="overflow-x-auto">
        <table className="table-auto w-full border-collapse">
          <thead>
            <tr className="border-b">
              <th className="px-4 py-2 text-left">ID</th>
              <th className="px-4 py-2 text-left">Created</th>
              <th className="px-4 py-2 text-left">Song Count</th>
              <th className="px-4 py-2 text-left">Progress</th>
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
                  <Progress value={job.completed ? 100 : job.progress * 100} />
                </td>
                <td className="px-4 py-2">
                  {job.completed
                    ? `Completed ${relative_time(new Date(job.completed))}`
                    : job.progress === 0
                      ? "Queued"
                      : "Running"}
                </td>
                <td className="px-4 py-2">
                  {job.progress === 0 && (
                    <Button
                      variant="outline"
                      onClick={() => handleDelete(job.id)}
                    >
                      <X /> Cancel
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
