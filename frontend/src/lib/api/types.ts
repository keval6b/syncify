export type SyncStatus = "pending" | "running" | "completed" | "failed";

export interface SyncRequest {
  id: string;
  user_id: string;
  song_count: number;
  status: SyncStatus;
  created: string;
  completed: string | null;
}

export interface User {
  id: string;
  display_name: string;
}
