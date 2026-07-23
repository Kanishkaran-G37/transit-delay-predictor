from django.conf import settings
from django.http import HttpResponse


class CorsMiddleware:
    """Allow a separate-origin frontend (the Streamlit map iframe) to call the API.

    The origin comes from CORS_ALLOW_ORIGIN, which defaults to '*' for local
    development. Set it to your real frontend origin in production.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.origin = getattr(settings, 'CORS_ALLOW_ORIGIN', '*')

    def __call__(self, request):
        if request.method == 'OPTIONS':
            response = HttpResponse()
        else:
            response = self.get_response(request)
        response['Access-Control-Allow-Origin'] = self.origin
        response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response['Access-Control-Allow-Headers'] = '*'
        if self.origin != '*':
            response['Vary'] = 'Origin'
        return response
