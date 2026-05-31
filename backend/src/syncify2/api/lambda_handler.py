from mangum import Mangum

from syncify2.api.app import app

_handler = Mangum(app, lifespan="off")


def handler(event, context):
    if event.get("source") == "warm-ping":
        return {"statusCode": 200}
    return _handler(event, context)
