from django.urls import path
from . import views

urlpatterns = [
    path('weather/', views.get_weather_view, name='weather'),
    path('traffic/', views.get_traffic_view, name='traffic'),
    path('prediction/', views.get_prediction, name='prediction'),
    path('vehicles/', views.get_live_vehicles_view, name='live-vehicles'),
    path('journey/', views.get_journey_view, name='journey'),
    path('stops-list/', views.get_stops_list, name='stops-list'),
]