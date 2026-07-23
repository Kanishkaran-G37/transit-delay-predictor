from django.http import HttpResponse


class CorsMiddleware:
    """Allow the Streamlit live-map iframe (a different origin) to fetch the API.

    Dev-only convenience: opens GET access to every origin. Tighten the allowed
    origin before any real deployment.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == 'OPTIONS':
            response = HttpResponse()
        else:
            response = self.get_response(request)
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response['Access-Control-Allow-Headers'] = '*'
        return response
