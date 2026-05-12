from django.urls import path
from . import views, admin_views

urlpatterns = [
    # ── Customer hub ──────────────────────────────────────────
    path("", views.hub_home, name="hub_home"),
    path("plan/", views.hub_plan, name="hub_plan"),

    # Plan Request API (customer side — no AI called here)
    path("plan/request/", views.request_plan, name="request_plan"),
    path("plan/request-status/", views.plan_request_status, name="plan_request_status"),
    path("post/<str:post_id>/feedback/", views.submit_feedback, name="submit_feedback"),
    path("post/<str:post_id>/approve/", views.approve_post, name="approve_post"),
    
    # Buffer OAuth endpoints
    path("buffer/auth/", views.buffer_auth, name="buffer_auth"),
    path("buffer/callback/", views.buffer_callback, name="buffer_callback"),

    # Keep legacy image endpoint for admin-triggered image gen
    path("plan/image/", views.generate_post_image, name="generate_post_image"),

    # Read-only approved plan endpoints (customer)
    path("plan/list/", views.list_plans, name="list_plans"),
    path("plan/<str:plan_id>/", views.get_plan, name="get_plan"),
    path("plan/<str:plan_id>/delete/", views.delete_plan, name="delete_plan"),

    # ── Admin panel ───────────────────────────────────────────
    path("admin-hub/", admin_views.admin_dashboard, name="admin_dashboard"),

    # Customer management
    path("admin-hub/customers/", admin_views.admin_customers, name="admin_customers"),
    path("admin-hub/customers/<int:user_id>/", admin_views.admin_customer_detail, name="admin_customer_detail"),
    path("admin-hub/customers/<int:user_id>/edit-profile/", admin_views.admin_edit_profile, name="admin_edit_profile"),

    # Plan request queue
    path("admin-hub/requests/", admin_views.admin_requests, name="admin_requests"),
    path("admin-hub/requests/<str:request_id>/", admin_views.admin_request_detail, name="admin_request_detail"),
    path("admin-hub/requests/<str:request_id>/set-status/", admin_views.admin_set_request_status, name="admin_set_request_status"),
    path("admin-hub/requests/<str:request_id>/generate/", admin_views.admin_generate_plan, name="admin_generate_plan"),

    # Plan / post editing
    path("admin-hub/plans/<str:plan_id>/", admin_views.admin_plan_detail, name="admin_plan_detail"),
    path("admin-hub/plans/<str:plan_id>/approve/", admin_views.admin_approve_plan, name="admin_approve_plan"),
    path("admin-hub/plans/<str:plan_id>/reject/", admin_views.admin_reject_plan, name="admin_reject_plan"),
    path("admin-hub/plans/<str:plan_id>/save-meta/", admin_views.admin_save_plan_meta, name="admin_save_plan_meta"),
    path("admin-hub/posts/<str:post_id>/save/", admin_views.admin_save_post, name="admin_save_post"),
    path("admin-hub/posts/<str:post_id>/generate-image/", admin_views.admin_generate_post_image, name="admin_generate_post_image"),
]