from django.db import models
from django.contrib.auth.hashers import make_password, check_password


class VideoUser(models.Model):
    """Completely separate user model for video hub — NOT linked to HubUser."""
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)  # hashed
    phone_number = models.CharField(max_length=20, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def verify_password(self, raw_password):
        return check_password(raw_password, self.password)

    def __str__(self):
        return self.email


class VideoProfile(models.Model):
    """Stores video onboarding form data, linked one-to-one with a VideoUser."""
    user = models.OneToOneField(VideoUser, on_delete=models.CASCADE, related_name='video_profile')

    brand_name = models.CharField(max_length=255, blank=True, default='')
    industry = models.CharField(max_length=255, blank=True, default='')
    target_platforms = models.JSONField(default=list, blank=True)
    target_audience = models.TextField(blank=True, default='')
    goals = models.TextField(blank=True, default='')

    video_style = models.CharField(max_length=100, blank=True, default='')
    tone = models.CharField(max_length=100, blank=True, default='')
    duration_pref = models.CharField(max_length=50, blank=True, default='5')
    music_preference = models.CharField(max_length=100, blank=True, default='none')
    voiceover = models.BooleanField(default=False)

    brand_colors = models.JSONField(default=list, blank=True)
    logo_url = models.URLField(max_length=1000, blank=True, default='')
    fonts = models.CharField(max_length=255, blank=True, default='')

    instagram = models.CharField(max_length=255, blank=True, default='')
    youtube = models.CharField(max_length=255, blank=True, default='')
    tiktok = models.CharField(max_length=255, blank=True, default='')
    facebook = models.CharField(max_length=255, blank=True, default='')
    linkedin = models.CharField(max_length=255, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.brand_name} - Video Profile ({self.user.email})"

    def to_brand_dict(self):
        return {
            "brand_name": self.brand_name,
            "industry": self.industry,
            "target_audience": self.target_audience,
            "goals": self.goals,
            "video_style": self.video_style,
            "tone": self.tone,
            "duration_pref": self.duration_pref,
            "music_preference": self.music_preference,
            "voiceover": self.voiceover,
            "brand_colors": self.brand_colors or [],
            "fonts": self.fonts,
            "target_platforms": self.target_platforms or [],
            "social_handles": {
                "instagram": self.instagram,
                "youtube": self.youtube,
                "tiktok": self.tiktok,
                "facebook": self.facebook,
                "linkedin": self.linkedin,
            },
        }


class GeneratedVideoPlan(models.Model):
    """A full AI-generated video plan for a date range — mirrors GeneratedPlan."""
    user = models.ForeignKey(VideoUser, on_delete=models.CASCADE, related_name='generated_video_plans')
    plan_id = models.CharField(max_length=30, unique=True)

    start_date = models.DateField()
    end_date = models.DateField()
    frequency = models.CharField(max_length=20, default='daily')
    platforms = models.JSONField(default=list)
    summary = models.TextField(blank=True, default='')
    themes = models.JSONField(default=list, blank=True)
    is_bookmarked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"VideoPlan {self.plan_id} ({self.user.email})"

    def to_dict(self):
        posts = [p.to_dict() for p in self.video_posts.all().order_by('sort_order')]
        return {
            "id": self.plan_id,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else "",
            "start_date": str(self.start_date),
            "end_date": str(self.end_date),
            "frequency": self.frequency,
            "platforms": self.platforms,
            "summary": self.summary,
            "themes": self.themes,
            "posts": posts,
        }


class GeneratedVideoPost(models.Model):
    """One video entry within a VideoPlan — mirrors GeneratedPost."""
    plan = models.ForeignKey(GeneratedVideoPlan, on_delete=models.CASCADE, related_name='video_posts')
    post_id = models.CharField(max_length=50)
    sort_order = models.IntegerField(default=0)

    # Schedule
    date = models.CharField(max_length=10)        # YYYY-MM-DD
    day_of_week = models.CharField(max_length=10, blank=True, default='')
    occasion = models.CharField(max_length=100, blank=True, default='')
    post_type = models.CharField(max_length=30, blank=True, default='')  # promotional | educational | festival | etc.

    # Content
    platforms = models.JSONField(default=list)
    title = models.CharField(max_length=255, blank=True, default='')
    script = models.TextField(blank=True, default='')         # Voiceover / narration script
    caption = models.TextField(blank=True, default='')        # Social caption
    hashtags = models.JSONField(default=list, blank=True)
    call_to_action = models.CharField(max_length=500, blank=True, default='')

    # Video Generation
    video_prompt = models.TextField(blank=True, default='')   # MiniMax video-01 prompt
    aspect_ratio = models.CharField(max_length=10, default='9:16')
    duration = models.CharField(max_length=10, default='5')
    color_palette_hint = models.JSONField(default=list, blank=True)

    # Generation Status
    video_url = models.URLField(max_length=1000, blank=True, default='')
    video_status = models.CharField(max_length=20, default='pending')  # pending | processing | ready | failed
    generation_task_id = models.CharField(max_length=150, blank=True, default='')

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
            "script": self.script,
            "caption": self.caption,
            "hashtags": self.hashtags,
            "call_to_action": self.call_to_action,
            "video_prompt": self.video_prompt,
            "aspect_ratio": self.aspect_ratio,
            "duration": self.duration,
            "color_palette_hint": self.color_palette_hint,
            "video_url": self.video_url,
            "video_status": self.video_status,
            "generation_task_id": self.generation_task_id,
        }
