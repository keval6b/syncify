import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Button } from "@/components/ui/button.tsx";
import { ApiError, getUser, handleLogin } from "@/lib/api/queries.ts";
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

export const Route = createFileRoute("/")({
  component: Index,
});

function Index() {
  const navigate = useNavigate();
  const [isLoggingIn, setIsLoggingIn] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getUser()
      .then((user) => {
        if (!cancelled && user) {
          navigate({ to: "/dashboard" });
        }
      })
      .catch((error: unknown) => {
        // Logged-out visitors are the normal case; the API answers 401.
        if (error instanceof ApiError && error.status === 401) return;
        throw error;
      });
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  return (
    <main className="flex-1 flex justify-center items-center">
      <div className="flex flex-col gap-4 items-center p-4">
        <h1 className="text-3xl font-bold">Syncify</h1>
        <p className="text-center">
          Sync your Spotify 'Liked Songs' playlist to a sharable one.
        </p>
        <Button
          disabled={isLoggingIn}
          onClick={() => {
            setIsLoggingIn(true);
            handleLogin().catch(() => setIsLoggingIn(false));
          }}
        >
          {isLoggingIn && <Loader2 className="animate-spin" />}
          Login with Spotify
        </Button>
      </div>
    </main>
  );
}
