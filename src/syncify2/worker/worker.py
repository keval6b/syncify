import posthog
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from syncify2.common import spotify, db
from syncify2.common.db import SyncRequest, User


def run():
    with Session(db.engine) as db_session:
        stmt = (
            select(SyncRequest)
            .join(User)
            .where(SyncRequest.completed == None)
            .order_by(SyncRequest.id.asc())
            .limit(1)
        )
        request = db_session.scalar(stmt)
        if not request:
            return

        client = spotify.get_client(request.user_id, db_session)
        if client is None:
            request.completed = func.now()
            db_session.merge(request)
            db_session.commit()
            return

        count = spotify.get_liked_count(client)
        if count != request.song_count:
            request.song_count = count
            db_session.merge(request)
            db_session.commit()

        if count == 0:
            request.completed = func.now()
            db_session.merge(request)
            db_session.commit()
            return

        print(f"Starting request {request.id} with {count} songs for {request.user_id}")
        for progress in spotify.sync(client):
            request.progress = progress / (
                count * 2
            )  # 1/2 for reading, 1/2 for writing
            db_session.merge(request)
            db_session.commit()

        request.completed = func.now()
        db_session.merge(request)
        db_session.commit()

        posthog.capture("sync_complete", distinct_id=request.user_id, properties={"song_count": count, "id": request.id})
        print(
            f"Sync reqeust {request.id} complete for {request.user_id}; {request.song_count} songs"
        )
