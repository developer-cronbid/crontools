from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.unified_login, name='login'),
    path('register/', views.unified_register, name='register'),
    path('logout/', views.unified_logout, name='logout'),
]
