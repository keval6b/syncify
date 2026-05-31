export interface SyncRequest {
  id: string;
  user_id: string;
  song_count: number;
  progress: number;
  created: string;
  completed: string | null;
}

export interface User {
  id: string;
  display_name: string;
}
