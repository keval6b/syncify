from pydantic import BaseModel


class UserResponse(BaseModel):
    id: str
    display_name: str
    playlist_url: str | None = None
