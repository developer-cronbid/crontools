from django.urls import path
from . import views

urlpatterns = [
    # Onboarding
    path("onboarding/", views.video_onboarding, name="video_onboarding"),

    # Main Dashboard / Plan View
    path("", views.video_plan, name="video_plan"),

    # Request APIs (customer side)
    path("plan/request/", views.request_video_plan, name="request_video_plan"),
    path("plan/request-status/", views.video_request_status, name="video_request_status"),
    
    path("plan/generate/", views.generate_video_plan, name="generate_video_plan"),
    path("plan/generate-video/", views.generate_post_video, name="generate_post_video"),

    # Status Polling
    path("plan/<str:plan_id>/post/<str:post_id>/status/", views.video_post_status, name="video_post_status"),

    # Plan CRUD
    path("plan/list/", views.list_video_plans, name="list_video_plans"),
    path("plan/<str:plan_id>/", views.get_video_plan, name="get_video_plan"),
    path("plan/<str:plan_id>/delete/", views.delete_video_plan, name="delete_video_plan"),
]
