import socket

from fastapi import APIRouter
from fastapi.responses import JSONResponse, RedirectResponse

from settings.config import settings

router = APIRouter(tags=["Operation Check"])


@router.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse(url=f"{settings.prefix_url}/docs")


@router.get("/operation")
def hello_world() -> JSONResponse:
    data = {"Hello": "World"}
    return JSONResponse(data)


@router.get("/operation/ip")
def get_status() -> JSONResponse:
    host = socket.gethostname()
    ip = socket.gethostbyname(host)

    response = {"hostname": host, "ip": ip}
    return JSONResponse(response)


@router.get("/operation/gzip-test")
def gzip_test() -> JSONResponse:
    large_data = {"data": "x" * 10000}
    return JSONResponse(large_data)
