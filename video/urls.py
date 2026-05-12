from django.urls import path
from . import views

urlpatterns = [
    # Onboarding
    path("onboarding/", views.video_onboarding, name="video_onboarding"),

    # Main Dashboard / Plan View
    path("", views.video_plan, name="video_plan"),

    # Request APIs (customer side — NO AI generation)
    path("plan/request/", views.request_video_plan, name="request_video_plan"),
    path("plan/request-status/", views.video_request_status, name="video_request_status"),

    # Plan CRUD (read-only for customer, only approved plans)
    path("plan/list/", views.list_video_plans, name="list_video_plans"),
    path("plan/<str:plan_id>/", views.get_video_plan, name="get_video_plan"),
    path("plan/<str:plan_id>/delete/", views.delete_video_plan, name="delete_video_plan"),

    # Post APIs
    path("post/<str:post_id>/approve/", views.approve_video_post, name="approve_video_post"),
    path("post/<str:post_id>/feedback/", views.submit_video_feedback, name="submit_video_feedback"),
]

