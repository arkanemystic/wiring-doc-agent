import azure.functions as func

from app.main import app as fastapi_app


# Azure Functions discovers this ASGI application when deployed.
app = func.AsgiFunctionApp(app=fastapi_app, http_auth_level=func.AuthLevel.ANONYMOUS)
