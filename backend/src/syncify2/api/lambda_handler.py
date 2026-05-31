from mangum import Mangum

from syncify2.api.app import app

handler = Mangum(app, lifespan="off")
