from django.urls import path
from . import views

urlpatterns = [
    path('nearby/', views.get_nearby_stops, name='nearby-stops'),
    path('route/<str:route_id>/', views.get_stops_for_route, name='route-stops'),
]