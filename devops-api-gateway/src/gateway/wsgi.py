"""Production WSGI entry point."""
from gateway.app import GatewaySettings, create_app
from gateway.http_upstream import HttpUpstream

application = create_app(HttpUpstream.from_env(), GatewaySettings.from_env())
