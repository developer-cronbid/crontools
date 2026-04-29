from django.urls import path
from . import views

urlpatterns = [
    path("", views.hub_home, name="hub_home"),
    path("plan/", views.hub_plan, name="hub_plan"),
    # path('chat-api/', views.chat_api, name='chat_api'),
    path("plan/generate/", views.generate_calendar, name="generate_calendar"),
]