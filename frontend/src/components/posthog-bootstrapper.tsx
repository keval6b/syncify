import { PostHogProvider } from "posthog-js/react";

const POSTHOG_KEY = import.meta.env.VITE_POSTHOG_API_KEY as string | undefined;
const POSTHOG_HOST =
  (import.meta.env.VITE_POSTHOG_HOST as string | undefined) ??
  "https://eu.i.posthog.com";

export default function PostHogBootstrapper({
  children,
}: {
  children: React.ReactNode;
}) {
  if (!POSTHOG_KEY) {
    return <>{children}</>;
  }

  return (
    <PostHogProvider
      apiKey={POSTHOG_KEY}
      options={{
        api_host: POSTHOG_HOST,
        defaults: "2025-05-24",
        capture_exceptions: true,
        debug: import.meta.env.MODE === "development",
      }}
    >
      {children}
    </PostHogProvider>
  );
}
