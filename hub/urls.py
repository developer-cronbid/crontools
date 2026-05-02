from django.urls import path
from . import views

urlpatterns = [
    path("", views.hub_home, name="hub_home"),
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("plan/", views.hub_plan, name="hub_plan"),

    # Plan API
    path("plan/generate/", views.generate_plan, name="generate_plan"),
    path("plan/image/", views.generate_post_image, name="generate_post_image"),
    path("plan/list/", views.list_plans, name="list_plans"),
    path("plan/<str:plan_id>/", views.get_plan, name="get_plan"),
    path("plan/<str:plan_id>/delete/", views.delete_plan, name="delete_plan"),
]