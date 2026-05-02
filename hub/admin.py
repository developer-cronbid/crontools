from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import HubUser, BusinessProfile, GeneratedPlan, GeneratedPost


@admin.register(HubUser)
class HubUserAdmin(UserAdmin):
    list_display = ('email', 'phone_number', 'is_active', 'date_joined')
    search_fields = ('email', 'phone_number')
    ordering = ('-date_joined',)


@admin.register(BusinessProfile)
class BusinessProfileAdmin(admin.ModelAdmin):
    list_display = ('business_name', 'user', 'industry', 'created_at')
    search_fields = ('business_name', 'user__email')


class GeneratedPostInline(admin.TabularInline):
    model = GeneratedPost
    extra = 0
    fields = ('date', 'post_type', 'platforms', 'image_status')
    readonly_fields = ('date', 'post_type', 'platforms', 'image_status')


@admin.register(GeneratedPlan)
class GeneratedPlanAdmin(admin.ModelAdmin):
    list_display = ('plan_id', 'user', 'start_date', 'end_date', 'created_at')
    search_fields = ('plan_id', 'user__email')
    list_filter = ('created_at',)
    inlines = [GeneratedPostInline]


@admin.register(GeneratedPost)
class GeneratedPostAdmin(admin.ModelAdmin):
    list_display = ('post_id', 'plan', 'date', 'post_type', 'image_status')
    search_fields = ('post_id', 'plan__plan_id', 'title')
    list_filter = ('image_status', 'post_type')
