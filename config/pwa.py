"""Serve the installable PWA frontend from Django, on the same origin as the API."""
import os
from django.conf import settings
from django.http import HttpResponse, FileResponse, Http404

PWA_DIR = os.path.join(settings.BASE_DIR, 'pwa')


def _path(name):
    p = os.path.join(PWA_DIR, name)
    if not os.path.exists(p):
        raise Http404(name)
    return p


def index(request):
    with open(_path('index.html'), encoding='utf-8') as f:
        return HttpResponse(f.read(), content_type='text/html')


def service_worker(request):
    with open(_path('sw.js'), encoding='utf-8') as f:
        resp = HttpResponse(f.read(), content_type='application/javascript')
    resp['Service-Worker-Allowed'] = '/'   # allow root scope
    resp['Cache-Control'] = 'no-cache'
    return resp


def manifest(request):
    with open(_path('manifest.webmanifest'), encoding='utf-8') as f:
        return HttpResponse(f.read(), content_type='application/manifest+json')


def icon(request, size):
    return FileResponse(open(_path(f'icon-{size}.png'), 'rb'), content_type='image/png')
