import { createRootRoute, Outlet } from "@tanstack/react-router";
import { TanStackRouterDevtools } from "@tanstack/react-router-devtools";
import { Toaster } from "@/components/ui/sonner.tsx";
import { Heart } from "lucide-react";

export const Route = createRootRoute({
  component: () => (
    <>
      <div className="container mx-auto min-h-screen flex flex-col">
        <div className="flex-1 flex flex-col">
          <Outlet />
        </div>
        <footer className="py-6 flex flex-col items-center gap-2">
          <p className="flex items-center gap-1 text-sm text-muted-foreground">
            Made with <Heart className="w-4 h-4 text-red-500 fill-red-500" /> by{" "}
            <a
              href="https://keval6b.com"
              target="_blank"
              className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              keval_6b
            </a>
          </p>
          <a
            href="https://github.com/keval6b/syncify"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <span>Source Code</span>
          </a>
        </footer>
      </div>
      <Toaster />
      <TanStackRouterDevtools />
    </>
  ),
});
