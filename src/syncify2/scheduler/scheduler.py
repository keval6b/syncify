from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.functions import count

from syncify2.common import spotify, db


def run():
    with Session(db.engine) as db_session:
        stmt = select(db.User).where(
            select(count())
            .where(
                db.SyncRequest.user_id == db.User.id, db.SyncRequest.completed == None
            )
            .scalar_subquery()
            == 0
        )
        users = db_session.scalars(stmt).all()

        new_requests = []
        for user in users:
            client = spotify.get_client(user.id, db_session, commit=False)
            liked_count = spotify.get_liked_count(client)
            if liked_count == 0:
                continue
            new_requests.append(db.SyncRequest(user_id=user.id, song_count=liked_count))

        db_session.add_all(new_requests)
        db_session.commit()

        print(f"Scheduled syncs for {len(users)} users at {datetime.now()}")
