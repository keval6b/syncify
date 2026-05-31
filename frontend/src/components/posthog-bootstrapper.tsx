import { useEffect, useState } from "react";
import { PostHogProvider } from "posthog-js/react";

type PostHogConfig = {
  host: string | null;
  public_key: string | null;
};

export default function PostHogBootstrapper({
  children,
}: {
  children: React.ReactNode;
}) {
  const [config, setConfig] = useState<PostHogConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/posthog")
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return (await r.json()) as PostHogConfig;
      })
      .then((cfg) => setConfig(cfg))
      .catch((e) => {
        console.error("Failed to load PostHog config", e);
        setError(String(e));
      });
  }, []);

  if (!config && !error) {
    // Minimal boot splash while fetching config
    return <div style={{ display: "none" }} />;
  }

  // If no public key is provided or an error occurred, render without analytics.
  if (!config?.public_key) {
    return <>{children}</>;
  }

  return (
    <PostHogProvider
      apiKey={config.public_key}
      options={{
        api_host: config.host ?? "https://eu.i.posthog.com",
        defaults: "2025-05-24",
        capture_exceptions: true,
        debug: import.meta.env.MODE === "development",
      }}
    >
      {children}
    </PostHogProvider>
  );
}
