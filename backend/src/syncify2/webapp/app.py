from fastapi import FastAPI

from syncify2.webapp import api_v1

app = FastAPI()
app.include_router(api_v1.router)
