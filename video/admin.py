from django.contrib import admin
from .models import VideoProfile, GeneratedVideoPlan, GeneratedVideoPost


@admin.register(VideoProfile)
class VideoProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'brand_name', 'industry', 'video_style', 'created_at')
    search_fields = ('user__email', 'brand_name', 'industry')


class GeneratedVideoPostInline(admin.TabularInline):
    model = GeneratedVideoPost
    extra = 0
    readonly_fields = ('post_id', 'date', 'title', 'video_status', 'video_url')
    fields = ('post_id', 'date', 'title', 'video_status', 'video_url')


@admin.register(GeneratedVideoPlan)
class GeneratedVideoPlanAdmin(admin.ModelAdmin):
    list_display = ('plan_id', 'user', 'start_date', 'end_date', 'frequency', 'created_at')
    search_fields = ('plan_id', 'user__email')
    list_filter = ('frequency', 'created_at')
    inlines = [GeneratedVideoPostInline]


@admin.register(GeneratedVideoPost)
class GeneratedVideoPostAdmin(admin.ModelAdmin):
    list_display = ('post_id', 'date', 'title', 'video_status', 'post_type')
    search_fields = ('post_id', 'title')
    list_filter = ('video_status', 'post_type')
