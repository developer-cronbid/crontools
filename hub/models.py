from django.db import models
from django.conf import settings

class BusinessProfile(models.Model):
    """Stores onboarding form data, linked one-to-one with a user."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='business_profile')

    # Business Profile
    business_name = models.CharField(max_length=255, blank=True, default='')
    industry = models.CharField(max_length=255, blank=True, default='')
    website = models.URLField(max_length=500, blank=True, default='')
    target_audience = models.TextField(blank=True, default='')
    goals = models.TextField(blank=True, default='')

    # Brand Assets
    logo_url = models.CharField(max_length=500, blank=True, default='')
    brand_colors = models.JSONField(default=list, blank=True)
    references = models.JSONField(default=list, blank=True)  # [{url, description}, ...]
    fonts = models.CharField(max_length=255, blank=True, default='')
    tone_of_voice = models.CharField(max_length=255, blank=True, default='')

    # Social Handles
    instagram = models.CharField(max_length=500, blank=True, default='')
    facebook = models.CharField(max_length=500, blank=True, default='')
    x_twitter = models.CharField(max_length=500, blank=True, default='')
    linkedin = models.CharField(max_length=500, blank=True, default='')
    discord = models.CharField(max_length=500, blank=True, default='')
    youtube = models.CharField(max_length=500, blank=True, default='')
    tiktok = models.CharField(max_length=500, blank=True, default='')

    # Buffer API Integration
    buffer_access_token = models.CharField(max_length=500, blank=True, null=True)
    buffer_refresh_token = models.CharField(max_length=500, blank=True, null=True)
    buffer_token_expires_at = models.DateTimeField(null=True, blank=True)
    buffer_channels = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.business_name} ({self.user.email})"

    def to_brand_dict(self):
        """Return the same nested dict format the AI logic expects."""
        return {
            "business_profile": {
                "name": self.business_name,
                "industry": self.industry,
                "website": self.website,
                "target_audience": self.target_audience,
                "goals": self.goals,
            },
            "brand_assets": {
                "logo_url": self.logo_url,
                "brand_colors": self.brand_colors or [],
                "references": self.references or [],
                "fonts": self.fonts,
                "tone_of_voice": self.tone_of_voice,
            },
            "social_handles": {
                "instagram": self.instagram,
                "facebook": self.facebook,
                "x_twitter": self.x_twitter,
                "linkedin": self.linkedin,
                "discord": self.discord,
                "youtube": self.youtube,
                "tiktok": self.tiktok,
            },
        }


class GeneratedPlan(models.Model):
    """Stores each plan generation, linked to the user."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='generated_plans')
    plan_id = models.CharField(max_length=30, unique=True)  # e.g. 20260430130208387207
    start_date = models.DateField()
    end_date = models.DateField()
    frequency = models.CharField(max_length=20, default='daily')
    platforms = models.JSONField(default=list)
    summary = models.TextField(blank=True, default='')
    themes = models.JSONField(default=list, blank=True)
    is_bookmarked = models.BooleanField(default=False)
    status        = models.CharField(max_length=20, default='approved') # 'draft' | 'approved' | 'rejected'
    admin_note    = models.TextField(blank=True, default='')
    created_at    = models.DateTimeField(auto_now_add=True)
    approved_at   = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Plan {self.plan_id} ({self.user.email})"

    def to_dict(self):
        """Return the same dict shape the frontend JS expects."""
        posts = [p.to_dict() for p in self.posts.all().order_by('sort_order')]
        return {
            "id": self.plan_id,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else "",
            "start_date": str(self.start_date),
            "end_date": str(self.end_date),
            "frequency": self.frequency,
            "platforms": self.platforms,
            "summary": self.summary,
            "themes": self.themes,
            "status": self.status,
            "admin_note": self.admin_note,
            "posts": posts,
        }


class GeneratedPost(models.Model):
    """Individual post within a plan."""
    plan = models.ForeignKey(GeneratedPlan, on_delete=models.CASCADE, related_name='posts')
    post_id = models.CharField(max_length=40)  # e.g. 20260430130208387207-0
    sort_order = models.IntegerField(default=0)
    date = models.CharField(max_length=10)  # YYYY-MM-DD
    day_of_week = models.CharField(max_length=10, blank=True, default='')
    occasion = models.CharField(max_length=100, blank=True, default='')
    post_type = models.CharField(max_length=20, blank=True, default='')
    platforms = models.JSONField(default=list)
    title = models.CharField(max_length=255, blank=True, default='')
    caption = models.TextField(blank=True, default='')
    hashtags = models.JSONField(default=list, blank=True)
    call_to_action = models.CharField(max_length=500, blank=True, default='')
    image_prompt = models.TextField(blank=True, default='')
    image_aspect_ratio = models.CharField(max_length=10, default='1:1')
    color_palette_hint = models.JSONField(default=list, blank=True)
    image_url = models.URLField(max_length=1000, blank=True, default='')
    image_status = models.CharField(max_length=20, default='pending')
    admin_post_note = models.TextField(blank=True, default='')

    def __str__(self):
        return f"{self.post_id}: {self.title}"

    def to_dict(self):
        return {
            "post_id": self.post_id,
            "date": self.date,
            "day_of_week": self.day_of_week,
            "occasion": self.occasion,
            "post_type": self.post_type,
            "platforms": self.platforms,
            "title": self.title,
            "caption": self.caption,
            "hashtags": self.hashtags,
            "call_to_action": self.call_to_action,
            "image_prompt": self.image_prompt,
            "image_aspect_ratio": self.image_aspect_ratio,
            "color_palette_hint": self.color_palette_hint,
            "image_url": self.image_url,
            "image_status": self.image_status,
            "admin_post_note": self.admin_post_note,
        }


class PlanRequest(models.Model):
    """Initial request from user, pending admin approval."""
    user           = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='plan_requests')
    request_id     = models.CharField(max_length=30, unique=True)
    start_date     = models.DateField()
    end_date       = models.DateField()
    frequency      = models.CharField(max_length=20, default='daily')
    platforms      = models.JSONField(default=list)
    platform_counts = models.JSONField(default=dict)
    status         = models.CharField(max_length=20, default='pending')
    extra_notes    = models.TextField(blank=True, default='')
    admin_note     = models.TextField(blank=True, default='')
    generated_plan = models.OneToOneField(GeneratedPlan, null=True, blank=True, on_delete=models.SET_NULL, related_name='plan_request')
    created_at     = models.DateTimeField(auto_now_add=True)

    def to_dict(self):
        return {
            "request_id": self.request_id,
            "status": self.status,
            "admin_note": self.admin_note,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else "",
        }

class VideoRequest(models.Model):
    """Pending video request."""
    user           = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='video_requests')
    request_id     = models.CharField(max_length=30, unique=True)
    start_date     = models.DateField()
    end_date       = models.DateField()
    frequency      = models.CharField(max_length=20, default='daily')
    platforms      = models.JSONField(default=list)
    platform_counts = models.JSONField(default=dict)
    status         = models.CharField(max_length=20, default='pending')
    extra_notes    = models.TextField(blank=True, default='')
    admin_note     = models.TextField(blank=True, default='')
    theme          = models.CharField(max_length=255, blank=True, default='')
    duration       = models.IntegerField(default=30)
    generated_plan = models.OneToOneField('video.GeneratedVideoPlan', null=True, blank=True, on_delete=models.SET_NULL, related_name='video_request')
    created_at     = models.DateTimeField(auto_now_add=True)

    def to_dict(self):
        return {
            "request_id": self.request_id,
            "status": self.status,
            "admin_note": self.admin_note,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else "",
        }

class Feedback(models.Model):
    """User feedback on specific posts."""
    post       = models.ForeignKey(GeneratedPost, on_delete=models.CASCADE, related_name='feedback_entries', null=True, blank=True)
    video_post = models.ForeignKey('video.GeneratedVideoPost', on_delete=models.CASCADE, related_name='feedback_entries', null=True, blank=True)
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    tags       = models.JSONField(default=list) # e.g. ['caption', 'image']
    notes      = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_resolved = models.BooleanField(default=False)
