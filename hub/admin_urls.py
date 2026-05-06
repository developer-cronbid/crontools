from django.urls import path
from . import admin_views

urlpatterns = [
    path("", admin_views.admin_dashboard, name="admin_dashboard"),
    path("requests/", admin_views.admin_requests, name="admin_requests"),
    path("requests/<str:request_id>/", admin_views.admin_request_detail, name="admin_request_detail"),
    path("requests/<str:request_id>/status/", admin_views.admin_set_request_status, name="admin_set_request_status"),
    path("requests/<str:request_id>/save-brief/", admin_views.admin_save_request_brief, name="admin_save_request_brief"),
    path("requests/<str:request_id>/generate/", admin_views.admin_generate_plan, name="admin_generate_plan"),
    
    path("customers/", admin_views.admin_customers, name="admin_customers"),
    path("customers/<int:user_id>/", admin_views.admin_customer_detail, name="admin_customer_detail"),
    path("customers/<int:user_id>/edit-profile/", admin_views.admin_edit_profile, name="admin_edit_profile"),
    
    path("plans/<str:plan_id>/", admin_views.admin_plan_detail, name="admin_plan_detail"),
    path("video-plans/<str:plan_id>/", admin_views.admin_video_plan_detail, name="admin_video_plan_detail"),
    path("plans/<str:plan_id>/approve/", admin_views.admin_approve_plan, name="admin_approve_plan"),
    path("plans/<str:plan_id>/reject/", admin_views.admin_reject_plan, name="admin_reject_plan"),
    path("plans/<str:plan_id>/delete/", admin_views.admin_delete_plan, name="admin_delete_plan"),
    path("plans/<str:plan_id>/save-meta/", admin_views.admin_save_plan_meta, name="admin_save_plan_meta"),
    
    path("posts/<str:post_id>/save/", admin_views.admin_save_post, name="admin_save_post"),
    path("posts/<str:post_id>/generate-image/", admin_views.admin_generate_post_image, name="admin_generate_post_image"),
    path("posts/<str:post_id>/upload-image/", admin_views.admin_upload_post_image, name="admin_upload_post_image"),
    path("posts/<str:post_id>/upload-video/", admin_views.admin_upload_post_video, name="admin_upload_post_video"),
    
    path("video-requests/", admin_views.admin_video_requests, name="admin_video_requests"),
    path("video-requests/<str:request_id>/", admin_views.admin_video_request_detail, name="admin_video_request_detail"),
]
