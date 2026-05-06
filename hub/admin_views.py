"""
hub/admin_views.py — Admin logic for managing plans and requests.
"""

import json
import os
import re
from datetime import datetime, timedelta, date
from functools import wraps

import requests
from django.contrib.auth import get_user_model
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.conf import settings

from django.core.files.storage import FileSystemStorage
from .models import BusinessProfile, GeneratedPlan, GeneratedPost, PlanRequest, VideoRequest
from video.models import GeneratedVideoPlan, GeneratedVideoPost

User = get_user_model()

# ── AIML API CONFIG ──────────────────────────────────────────────────────────
AIML_API_KEY    = "1caa12b3cd1787b67fc7c2c6b60d065b"
AIML_CHAT_URL   = "https://api.aimlapi.com/v1/chat/completions"
AIML_IMAGE_URL  = "https://api.aimlapi.com/v1/images/generations"
AIML_TEXT_MODEL = "anthropic/claude-opus-4-6"
AIML_IMAGE_MODEL = "google/nano-banana-pro"

# ── Auth decorator ────────────────────────────────────────────────────────────
def staff_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/accounts/login/?next={request.path}')
        if not request.user.is_staff and not request.user.is_superuser:
            # Fallback check: if the username is one we know should be admin
            if request.user.username in ['Nandhishwaran', 'admin', 'Praveen Patel']:
                return view_func(request, *args, **kwargs)
            return HttpResponseForbidden(f"Admin access only. You are logged in as {request.user.username}")
        return view_func(request, *args, **kwargs)
    return _wrapped

# ── Shared helpers ────────────────────────────────────────────────────────────
def _extract_json_block(text):
    if not text:
        return None
    text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.IGNORECASE)
    text = re.sub(r'\s*```$', '', text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in [('[', ']'), ('{', '}')]:
        start = text.find(opener)
        if start == -1:
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if esc:
                esc = False; continue
            if ch == '\\':
                esc = True; continue
            if ch == '"':
                in_str = not in_str; continue
            if in_str:
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
    return None

def _call_claude(system_prompt, user_prompt, max_tokens=16000, temperature=0.65):
    headers = {
        "Authorization": f"Bearer {AIML_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": AIML_TEXT_MODEL,
        "messages": [{"role": "user", "content": user_prompt}],
        "system": system_prompt,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    r = requests.post(AIML_CHAT_URL, headers=headers, json=payload, timeout=180)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

# ════════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ════════════════════════════════════════════════════════════════════════════════
@staff_required
def admin_dashboard(request):
    pending_requests = PlanRequest.objects.filter(status='pending').count()
    working_requests = PlanRequest.objects.filter(status='working').count()
    total_customers  = BusinessProfile.objects.count()
    approved_plans   = GeneratedPlan.objects.filter(status='approved').count()
    recent_requests  = PlanRequest.objects.select_related('user').order_by('-created_at')[:8]

    return render(request, "hub/admin_panel.html", {
        "section": "dashboard",
        "stats": {
            "pending":   pending_requests,
            "working":   working_requests,
            "customers": total_customers,
            "approved":  approved_plans,
        },
        "recent_requests": recent_requests,
    })

# ════════════════════════════════════════════════════════════════════════════════
# CUSTOMER LIST
# ════════════════════════════════════════════════════════════════════════════════
@staff_required
def admin_customers(request):
    profiles = BusinessProfile.objects.select_related('user').order_by('-created_at')
    return render(request, "hub/admin_panel.html", {
        "section":  "customers",
        "profiles": profiles,
    })

@staff_required
def admin_customer_detail(request, user_id):
    user    = get_object_or_404(User, pk=user_id)
    profile = getattr(user, 'business_profile', None)
    requests_qs = PlanRequest.objects.filter(user=user).order_by('-created_at')
    plans_qs    = GeneratedPlan.objects.filter(user=user).order_by('-created_at')

    return render(request, "hub/admin_panel.html", {
        "section":   "customer_detail",
        "cust":      user,
        "profile":   profile,
        "requests":  requests_qs,
        "plans":     plans_qs,
    })

@staff_required
def admin_edit_profile(request, user_id):
    user    = get_object_or_404(User, pk=user_id)
    profile = getattr(user, 'business_profile', None)

    if request.method == 'POST':
        data = json.loads(request.body.decode('utf-8'))
        if profile is None:
            profile = BusinessProfile(user=user)
        profile.business_name   = data.get('business_name', profile.business_name)
        profile.industry        = data.get('industry', profile.industry)
        profile.website         = data.get('website', profile.website)
        profile.target_audience = data.get('target_audience', profile.target_audience)
        profile.goals           = data.get('goals', profile.goals)
        profile.logo_url        = data.get('logo_url', profile.logo_url)
        profile.brand_colors    = data.get('brand_colors', profile.brand_colors)
        profile.fonts           = data.get('fonts', profile.fonts)
        profile.tone_of_voice   = data.get('tone_of_voice', profile.tone_of_voice)
        profile.save()
        return JsonResponse({"ok": True, "message": "Profile updated"})

    if profile:
        brand = profile.to_brand_dict()
    else:
        brand = {}
    return JsonResponse({"profile": brand})

# ════════════════════════════════════════════════════════════════════════════════
# REQUEST QUEUE
# ════════════════════════════════════════════════════════════════════════════════
@staff_required
def admin_requests(request):
    qs = PlanRequest.objects.select_related('user', 'generated_plan').order_by('-created_at')
    return render(request, "hub/admin_panel.html", {
        "section":       "requests",
        "plan_requests": qs,
    })

@staff_required
def admin_request_detail(request, request_id):
    plan_req = get_object_or_404(PlanRequest, request_id=request_id)
    profile  = getattr(plan_req.user, 'business_profile', None)
    # Prepare platforms with counts for the template
    plat_data = []
    counts = plan_req.platform_counts or {}
    for p in (plan_req.platforms or []):
        plat_data.append({
            "name": p,
            "count": counts.get(p, 1)
        })

    return render(request, "hub/admin_panel.html", {
        "section":   "request_detail",
        "req":       plan_req,
        "profile":   profile,
        "platforms_with_counts": plat_data,
    })

@staff_required
@require_POST
@csrf_exempt
def admin_set_request_status(request, request_id):
    # Try PlanRequest first, then VideoRequest
    plan_req = PlanRequest.objects.filter(request_id=request_id).first()
    if not plan_req:
        plan_req = VideoRequest.objects.filter(request_id=request_id).first()
    
    if not plan_req:
        return JsonResponse({"error": "Request not found"}, status=404)

    body = json.loads(request.body.decode('utf-8'))
    plan_req.status = body.get('status', plan_req.status)
    plan_req.admin_note = body.get('note', plan_req.admin_note)
    plan_req.save()
    return JsonResponse({"ok": True, "status": plan_req.status})

@staff_required
@require_POST
@csrf_exempt
def admin_save_request_brief(request, request_id):
    """Save both the User's Business Profile and the Request's internal notes."""
    # Try PlanRequest first, then VideoRequest
    plan_req = PlanRequest.objects.filter(request_id=request_id).first()
    if not plan_req:
        plan_req = VideoRequest.objects.filter(request_id=request_id).first()
    
    if not plan_req:
        return JsonResponse({"error": "Request not found"}, status=404)

    profile  = getattr(plan_req.user, 'business_profile', None)
    data     = json.loads(request.body.decode('utf-8'))
    
    # 1. Update Request specific notes & Generation settings
    plan_req.extra_notes = data.get('extra_notes', plan_req.extra_notes)
    plan_req.admin_note  = data.get('admin_note', plan_req.admin_note)
    
    if 'start_date' in data: plan_req.start_date = data['start_date']
    if 'end_date' in data:   plan_req.end_date   = data['end_date']
    if 'frequency' in data:  plan_req.frequency  = data['frequency']
    if 'platform_counts' in data: plan_req.platform_counts = data['platform_counts']
    
    # Video-specific fields
    if hasattr(plan_req, 'theme') and 'theme' in data:
        plan_req.theme = data['theme']
    if hasattr(plan_req, 'duration') and 'duration' in data:
        plan_req.duration = data['duration']

    plan_req.save()
    
    # 2. Update the Global Business Profile
    if profile is None:
        profile = BusinessProfile(user=plan_req.user)
    
    profile.business_name   = data.get('business_name', profile.business_name)
    profile.industry        = data.get('industry', profile.industry)
    profile.website         = data.get('website', profile.website)
    profile.target_audience = data.get('target_audience', profile.target_audience)
    profile.goals           = data.get('goals', profile.goals)
    profile.brand_colors    = data.get('brand_colors', profile.brand_colors)
    profile.tone_of_voice   = data.get('tone_of_voice', profile.tone_of_voice)
    
    # Social Handles
    profile.instagram = data.get('instagram', profile.instagram)
    profile.facebook  = data.get('facebook', profile.facebook)
    profile.tiktok    = data.get('tiktok', profile.tiktok)
    profile.linkedin  = data.get('linkedin', profile.linkedin)
    profile.youtube   = data.get('youtube', profile.youtube)
    profile.x_twitter = data.get('x_twitter', profile.x_twitter)
    
    profile.save()
    
    return JsonResponse({"ok": True, "message": "All briefing data saved."})

@staff_required
@require_POST
@csrf_exempt
def admin_generate_plan(request, request_id):
    # Try PlanRequest first, then VideoRequest
    plan_req = PlanRequest.objects.filter(request_id=request_id).first()
    is_video_req = False
    if not plan_req:
        plan_req = VideoRequest.objects.filter(request_id=request_id).first()
        is_video_req = True
    
    if not plan_req:
        return JsonResponse({"error": "Request not found."}, status=404)

    profile  = getattr(plan_req.user, 'business_profile', None)
    if not profile:
        return JsonResponse({"error": "Customer has no brand profile yet."}, status=400)

    # Mark as working
    plan_req.status = 'working'
    plan_req.save()

    brand     = profile.to_brand_dict()
    start_d   = plan_req.start_date
    end_d     = plan_req.end_date
    frequency = plan_req.frequency
    platforms = plan_req.platforms
    
    if is_video_req:
        # ── VIDEO GENERATION LOGIC ──────────────────────────────────────────
        system_prompt = (
            "You are a senior video director. Produce valid JSON video plans. No prose."
        )
        user_prompt = f"""
Build a daily video content plan for:
Name: {brand.get('business_profile', {}).get('name','')}
Theme: {getattr(plan_req, 'theme', 'Brand Story')}
Duration: {getattr(plan_req, 'duration', 30)}s
Start: {start_d}
End: {end_d}
Frequency: {frequency}
Platforms: {', '.join(platforms)}

Schema:
{{
  "summary": "overall strategy",
  "posts": [
    {{
      "date": "YYYY-MM-DD",
      "title": "Scene Title",
      "caption": "Video Caption",
      "script": "Voiceover/Dialogue script",
      "video_prompt": "Detailed AI video generation prompt",
      "hashtags": ["#tag1"]
    }}
  ]
}}
"""
        try:
            raw = _call_claude(system_prompt, user_prompt)
            parsed = _extract_json_block(raw)
            if not parsed or "posts" not in parsed:
                raise ValueError("Invalid AI response")

            plan_id = "v-" + datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
            plan = GeneratedVideoPlan.objects.create(
                user=plan_req.user,
                plan_id=plan_id,
                start_date=start_d,
                end_date=end_d,
                frequency=frequency,
                platforms=platforms,
                summary=parsed.get("summary", ""),
                status='draft'
            )

            for i, p in enumerate(parsed.get("posts", [])):
                GeneratedVideoPost.objects.create(
                    plan=plan,
                    post_id=f"{plan_id}-{i}",
                    sort_order=i,
                    date=p.get("date", ""),
                    title=p.get("title", ""),
                    caption=p.get("caption", ""),
                    script=p.get("script", ""),
                    video_prompt=p.get("video_prompt", ""),
                    hashtags=p.get("hashtags", []),
                    video_status="pending"
                )

            if hasattr(plan_req, 'generated_plan'):
                 plan_req.generated_plan = plan
            
            plan_req.save()
            return JsonResponse({"ok": True, "plan_id": plan_id, "type": "video"})

        except Exception as e:
            plan_req.status = 'pending'
            plan_req.save()
            return JsonResponse({"error": str(e)}, status=500)

    else:
        # ── IMAGE/POST GENERATION LOGIC ─────────────────────────────────────
        system_prompt = (
            "You are a senior social media strategist for Indian SMB brands. "
            "You produce valid JSON social media plans. No prose."
        )
        bp = brand.get("business_profile", {})
        ba = brand.get("brand_assets", {})

        user_prompt = f"""
Build a daily social media plan for:
Name: {bp.get('name','')}
Industry: {bp.get('industry','')}
Goals: {bp.get('goals','')}
Colors: {', '.join(ba.get('brand_colors', []))}
Tone: {ba.get('tone_of_voice','')}

Start: {start_d}
End: {end_d}
Frequency: {frequency}
Platforms: {', '.join(platforms)}

Schema:
{{
  "summary": "strategic summary",
  "themes": ["theme 1", ...],
  "posts": [
    {{
      "date": "YYYY-MM-DD",
      "day_of_week": "Monday",
      "occasion": "Topic",
      "post_type": "educational"|"offer"|"festival",
      "platforms": ["instagram"],
      "title": "Title",
      "caption": "Full caption",
      "hashtags": ["#tag1"],
      "call_to_action": "CTA",
      "image_prompt": "detailed image generation prompt",
      "image_aspect_ratio": "1:1"
    }}
  ]
}}
"""
        try:
            raw = _call_claude(system_prompt, user_prompt)
            parsed = _extract_json_block(raw)
            if not parsed or "posts" not in parsed:
                raise ValueError("Invalid AI response")

            plan_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
            plan = GeneratedPlan.objects.create(
                user=plan_req.user,
                plan_id=plan_id,
                start_date=start_d,
                end_date=end_d,
                frequency=frequency,
                platforms=platforms,
                summary=parsed.get("summary", ""),
                themes=parsed.get("themes", []),
                status='draft'
            )

            for i, p in enumerate(parsed.get("posts", [])):
                GeneratedPost.objects.create(
                    plan=plan,
                    post_id=f"{plan_id}-{i}",
                    sort_order=i,
                    date=p.get("date", ""),
                    day_of_week=p.get("day_of_week", ""),
                    occasion=p.get("occasion", ""),
                    post_type=p.get("post_type", ""),
                    platforms=p.get("platforms", []),
                    title=p.get("title", ""),
                    caption=p.get("caption", ""),
                    hashtags=p.get("hashtags", []),
                    call_to_action=p.get("call_to_action", ""),
                    image_prompt=p.get("image_prompt", ""),
                    image_aspect_ratio=p.get("image_aspect_ratio", "1:1"),
                    image_url="",
                    image_status="pending"
                )

            plan_req.generated_plan = plan
            plan_req.save()
            return JsonResponse({"ok": True, "plan_id": plan_id, "type": "image"})

        except Exception as e:
            plan_req.status = 'pending'
            plan_req.save()
            return JsonResponse({"error": str(e)}, status=500)

# ════════════════════════════════════════════════════════════════════════════════
# VIDEO REQUESTS
# ════════════════════════════════════════════════════════════════════════════════
@staff_required
def admin_video_requests(request):
    qs = VideoRequest.objects.select_related('user').order_by('-created_at')
    return render(request, "hub/admin_panel.html", {
        "section": "video_requests",
        "video_requests": qs,
    })

@staff_required
def admin_video_request_detail(request, request_id):
    video_req = get_object_or_404(VideoRequest, request_id=request_id)
    profile   = getattr(video_req.user, 'business_profile', None)
    
    plat_data = []
    counts = video_req.platform_counts or {}
    for p in (video_req.platforms or []):
        plat_data.append({
            "name": p,
            "count": counts.get(p, 1)
        })

    return render(request, "hub/admin_panel.html", {
        "section":   "video_request_detail",
        "req":        video_req,
        "profile":   profile,
        "platforms_with_counts": plat_data,
    })

# ════════════════════════════════════════════════════════════════════════════════
# PLAN DETAIL & APPROVAL
# ════════════════════════════════════════════════════════════════════════════════
@staff_required
def admin_plan_detail(request, plan_id):
    plan    = get_object_or_404(GeneratedPlan, plan_id=plan_id)
    posts   = plan.posts.all().order_by('sort_order')
    profile = getattr(plan.user, 'business_profile', None)
    
    # Try to find the originating request
    plan_req = getattr(plan, 'plan_request', None)
    plat_data = []
    if plan_req:
        counts = plan_req.platform_counts or {}
        for p in (plan_req.platforms or []):
            plat_data.append({"name": p, "count": counts.get(p, 1)})

    return render(request, "hub/admin_panel.html", {
        "section":   "plan_detail",
        "plan":      plan,
        "posts":     posts,
        "profile":   profile,
        "req":       plan_req,
        "platforms_with_counts": plat_data,
    })

@staff_required
def admin_video_plan_detail(request, plan_id):
    plan    = get_object_or_404(GeneratedVideoPlan, plan_id=plan_id)
    posts   = plan.video_posts.all().order_by('sort_order')
    return render(request, "hub/admin_panel.html", {
        "section": "video_plan_detail",
        "plan":    plan,
        "posts":   posts,
    })

@staff_required
@require_POST
@csrf_exempt
def admin_approve_plan(request, plan_id):
    # Try Image Plan
    plan = GeneratedPlan.objects.filter(plan_id=plan_id).first()
    if not plan:
        # Try Video Plan
        plan = GeneratedVideoPlan.objects.filter(plan_id=plan_id).first()
    
    if not plan:
        return JsonResponse({"error": "Plan not found"}, status=404)

    body = json.loads(request.body.decode('utf-8')) if request.body else {}
    plan.status = 'approved'
    plan.approved_at = timezone.now()
    plan.admin_note = body.get('note', plan.admin_note)
    plan.save()

    # Link back to request
    if hasattr(plan, 'plan_request') and plan.plan_request:
        plan.plan_request.status = 'approved'
        plan.plan_request.admin_note = plan.admin_note
        plan.plan_request.save()
    elif hasattr(plan, 'video_request') and plan.video_request:
        plan.video_request.status = 'approved'
        plan.video_request.admin_note = plan.admin_note
        plan.video_request.save()

    return JsonResponse({"ok": True})

@staff_required
@require_POST
@csrf_exempt
def admin_reject_plan(request, plan_id):
    # Try Image Plan
    plan = GeneratedPlan.objects.filter(plan_id=plan_id).first()
    if not plan:
        # Try Video Plan
        plan = GeneratedVideoPlan.objects.filter(plan_id=plan_id).first()
    
    if not plan:
        return JsonResponse({"error": "Plan not found"}, status=404)

    body = json.loads(request.body.decode('utf-8')) if request.body else {}
    plan.status = 'rejected'
    plan.admin_note = body.get('note', plan.admin_note)
    plan.save()

    # Link back to request
    if hasattr(plan, 'plan_request') and plan.plan_request:
        plan.plan_request.status = 'rejected'
        plan.plan_request.admin_note = plan.admin_note
        plan.plan_request.save()
    elif hasattr(plan, 'video_request') and plan.video_request:
        plan.video_request.status = 'rejected'
        plan.video_request.admin_note = plan.admin_note
        plan.video_request.save()

    return JsonResponse({"ok": True})

@staff_required
@require_POST
@csrf_exempt
def admin_delete_plan(request, plan_id):
    # Try Image Plan
    plan = GeneratedPlan.objects.filter(plan_id=plan_id).first()
    if plan:
        # Revert linked request if exists
        if hasattr(plan, 'plan_request') and plan.plan_request:
            plan.plan_request.status = 'pending'
            plan.plan_request.generated_plan = None
            plan.plan_request.save()
        plan.delete()
        return JsonResponse({"ok": True})

    # Try Video Plan
    vplan = GeneratedVideoPlan.objects.filter(plan_id=plan_id).first()
    if vplan:
        # Revert linked request if exists
        if hasattr(vplan, 'video_request') and vplan.video_request:
            vplan.video_request.status = 'pending'
            vplan.video_request.generated_plan = None
            vplan.video_request.save()
        vplan.delete()
        return JsonResponse({"ok": True})

    return JsonResponse({"error": "Plan not found"}, status=404)

@staff_required
@require_POST
@csrf_exempt
def admin_save_plan_meta(request, plan_id):
    plan = get_object_or_404(GeneratedPlan, plan_id=plan_id)
    body = json.loads(request.body.decode('utf-8'))
    plan.summary = body.get('summary', plan.summary)
    plan.save()
    return JsonResponse({"ok": True})

@staff_required
@require_POST
@csrf_exempt
def admin_save_post(request, post_id):
    # Try Image post first, then Video post
    post = GeneratedPost.objects.filter(post_id=post_id).first()
    if not post:
        post = GeneratedVideoPost.objects.filter(post_id=post_id).first()
    
    if not post:
        return JsonResponse({"error": "Post not found"}, status=404)

    body = json.loads(request.body.decode('utf-8'))
    # Standard fields for both
    fields = ['title', 'caption', 'image_prompt', 'video_prompt', 'script', 'admin_post_note', 'occasion', 'call_to_action','date']
    for field in fields:
        if field in body:
            setattr(post, field, body[field])
    
    # Special handling for hashtags (ensure it's a list)
    if 'hashtags' in body:
        tags = body['hashtags']
        if isinstance(tags, str):
            try:
                # Try to parse if it's JSON string like ["tag1", "tag2"]
                import json
                parsed = json.loads(tags)
                if isinstance(parsed, list):
                    post.hashtags = parsed
                else:
                    post.hashtags = [t.strip() for t in tags.replace('[','').replace(']','').replace('"','').split(',') if t.strip()]
            except:
                # Fallback to simple split
                post.hashtags = [t.strip() for t in tags.split(',') if t.strip()]
        else:
            post.hashtags = tags

    post.save()
    return JsonResponse({"ok": True})

@staff_required
@require_POST
@csrf_exempt
def admin_generate_post_image(request, post_id):
    post = get_object_or_404(GeneratedPost, post_id=post_id)
    body = json.loads(request.body.decode('utf-8'))
    prompt = body.get('custom_prompt') or post.image_prompt
    
    if not prompt:
        return JsonResponse({"error": "No prompt"}, status=400)

    try:
        headers = {"Authorization": f"Bearer {AIML_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": AIML_IMAGE_MODEL,
            "prompt": prompt,
            "aspect_ratio": post.image_aspect_ratio or "1:1",
            "resolution": "2K"
        }
        r = requests.post(AIML_IMAGE_URL, headers=headers, json=payload, timeout=240)
        r.raise_for_status()
        url = r.json()["data"][0]["url"]
        
        post.image_url = url
        post.image_status = 'ready'
        post.save()
        return JsonResponse({"ok": True, "image_url": url})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

@staff_required
@require_POST
def admin_upload_post_image(request, post_id):
    post = get_object_or_404(GeneratedPost, post_id=post_id)
    if 'image_file' not in request.FILES:
        return JsonResponse({"error": "No file uploaded"}, status=400)
    
    img = request.FILES['image_file']
    fs = FileSystemStorage()
    filename = fs.save(f"posts/images/{img.name}", img)
    url = fs.url(filename)
    
    post.image_url = url
    post.image_status = 'ready'
    post.save()
    return JsonResponse({"ok": True, "image_url": url})

@staff_required
@require_POST
def admin_upload_post_video(request, post_id):
    # Try both GeneratedVideoPost and GeneratedPost (if it supports video)
    # But usually Video has its own model
    post = get_object_or_404(GeneratedVideoPost, post_id=post_id)
    if 'video_file' not in request.FILES:
        return JsonResponse({"error": "No file uploaded"}, status=400)
    
    vid = request.FILES['video_file']
    fs = FileSystemStorage()
    filename = fs.save(f"posts/videos/{vid.name}", vid)
    url = fs.url(filename)
    
    post.video_url = url
    post.video_status = 'ready'
    post.save()
    return JsonResponse({"ok": True, "video_url": url})
