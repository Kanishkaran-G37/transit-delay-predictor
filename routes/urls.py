from django.urls import path
from . import views

urlpatterns = [
    path('', views.get_all_routes, name='all-routes'),
    path('<str:route_id>/', views.get_route_detail, name='route-detail'),
]