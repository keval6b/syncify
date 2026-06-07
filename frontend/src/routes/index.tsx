import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Button } from "@/components/ui/button.tsx";
import { getUser, handleLogin } from "@/lib/api/queries.ts";
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

export const Route = createFileRoute("/")({
  component: Index,
});

function Index() {
  const navigate = useNavigate();
  const [isLoggingIn, setIsLoggingIn] = useState(false);

  useEffect(() => {
    getUser()
      .then((user) => {
        if (user) {
          navigate({ to: "/dashboard" }).then();
        }
      })
      .catch();
  }, []);

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
