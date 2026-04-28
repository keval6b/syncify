import { SyncRequest, User } from "./types.ts";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function throwApiError(response: Response): Promise<never> {
  let detail = "Request failed";
  try {
    const payload = await response.json();
    if (payload?.detail) {
      detail = payload.detail;
    }
  } catch {
    // Keep default message when response body isn't JSON
  }
  throw new ApiError(response.status, detail);
}

export async function enqueueJob() {
  const response = await fetch("/api/v1/jobs", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
  });
  if (!response.ok) {
    await throwApiError(response);
  }
}

export async function getJobs() {
  const response = await fetch("/api/v1/jobs");
  if (!response.ok) {
    await throwApiError(response);
  }
  return (await response.json()) as SyncRequest[];
}

export async function deleteJob(id: number) {
  const response = await fetch(`/api/v1/jobs/${id}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    await throwApiError(response);
  }
}

export async function getUser(): Promise<User> {
  const response = await fetch("/api/v1/auth/user", {
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return await response.json();
}

export async function handleLogin() {
  const response = await fetch("/api/v1/auth/login");
  if (response.ok) {
    window.location.assign(await response.json());
  } else {
    await throwApiError(response);
  }
}

export async function handleLogout() {
  const response = await fetch("/api/v1/auth/logout");
  if (response.ok) {
    window.location.reload();
  } else {
    await throwApiError(response);
  }
}

export async function handleDeleteAccount() {
  const response = await fetch("/api/v1/auth/delete", {
    method: "POST",
  });
  if (response.ok) {
     window.location.assign("/")
  } else {
    await throwApiError(response);
  }
}
