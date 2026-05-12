import json
import os
from datetime import datetime, timedelta, date

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.core.files.storage import FileSystemStorage
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required

import requests
from hub.models import BusinessProfile, VideoRequest, Feedback
from .models import VideoProfile, GeneratedVideoPlan, GeneratedVideoPost
from hub.views import refresh_buffer_token

# ============================================================
# VIDEO ONBOARDING
# ============================================================
@login_required
def video_onboarding(request):
    """Multi-step brand setup form for video. Redirects to video_plan if already set up."""
    if hasattr(request.user, 'video_profile'):
        return redirect('video_plan')

    if request.method == 'POST':
        fs = FileSystemStorage()

        # Handle optional logo upload
        logo_path = ""
        logo_file = request.FILES.get('logo')
        if logo_file:
            filename = fs.save(f"video_logos/{logo_file.name}", logo_file)
            logo_path = fs.url(filename)

        profile = VideoProfile.objects.create(
            user=request.user,
            brand_name=request.POST.get('brand_name', ''),
            industry=request.POST.get('industry', ''),
            target_audience=request.POST.get('target_audience', ''),
            goals=request.POST.get('goals', ''),
            video_style=request.POST.get('video_style', ''),
            tone=request.POST.get('tone', ''),
            duration_pref=request.POST.get('duration_pref', '5'),
            music_preference=request.POST.get('music_preference', 'none'),
            voiceover=request.POST.get('voiceover') == 'true',
            fonts=request.POST.get('fonts', ''),
            logo_url=logo_path,
            instagram=request.POST.get('instagram', ''),
            youtube=request.POST.get('youtube', ''),
            tiktok=request.POST.get('tiktok', ''),
            facebook=request.POST.get('facebook', ''),
            linkedin=request.POST.get('linkedin', ''),
        )
        profile.target_platforms = request.POST.getlist('target_platform')
        profile.brand_colors = request.POST.getlist('brand_colors')
        profile.save()

        return redirect('video_plan')

    return render(request, 'video/video_onboarding.html')


# ============================================================
# VIDEO PLAN DASHBOARD
# ============================================================
@login_required
def video_plan(request):
    """Main video studio dashboard — shows form + past plans (only approved ones)."""
    if not hasattr(request.user, 'video_profile'):
        return redirect('video_onboarding')

    profile = request.user.video_profile
    brand = profile.to_brand_dict()
    
    # Only show approved video plans to customers (same as image flow)
    db_plans = GeneratedVideoPlan.objects.filter(user=request.user, status='approved')
    plans = [p.to_dict() for p in db_plans]
    plans_json = json.dumps(plans)

    # Check for pending requests (video)
    pending_video_requests = VideoRequest.objects.filter(
        user=request.user, 
        status__in=['pending', 'working']
    ).exists()

    return render(request, 'video/video_plan.html', {
        'brand': brand,
        'brand_obj': profile,
        'plans': plans,
        'plans_json': plans_json,
        'has_brand': True,
        'pending_video_requests': pending_video_requests,
    })


# ============================================================
# VIDEO REQUEST API (Customer side - NO AI generation!)
# ============================================================
@login_required
def request_video_plan(request):
    """
    User requests a video plan — creates a VideoRequest, NO AI called.
    Same flow as image generation's request_plan().
    """
    if request.method == 'POST':
        body = json.loads(request.body.decode('utf-8'))
        request_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        
        # Parse video counts per platform (like photo_counts in image flow)
        video_counts = body.get('video_counts', {})
        if not video_counts and body.get('platforms'):
            # Default: 1 video per platform if not specified
            video_counts = {p: 1 for p in body.get('platforms', [])}
        
        VideoRequest.objects.create(
            user=request.user,
            request_id=request_id,
            start_date=body.get('start_date'),
            end_date=body.get('end_date'),
            frequency=body.get('frequency', 'daily'),
            platforms=body.get('platforms', []),
            platform_counts=video_counts,
            extra_notes=body.get('notes', ''),
            theme=body.get('theme', 'Brand Story'),
            duration=body.get('duration', 30),
            status='pending'
        )
        return JsonResponse({
            "ok": True, 
            "request_id": request_id, 
            "message": "Video plan requested. Admin will review within 24h."
        })
    return JsonResponse({"error": "Method not allowed"}, status=405)


@login_required
def video_request_status(request):
    """Check status of pending video requests (similar to plan_request_status)."""
    reqs = VideoRequest.objects.filter(user=request.user).exclude(status='approved')
    return JsonResponse({
        "requests": [{
            "request_id": r.request_id, 
            "status": r.status,
            "admin_note": r.admin_note,
            "created_at": r.created_at.isoformat()
        } for r in reqs]
    })


# ============================================================
# APPROVED PLANS READ-ONLY (Customer view)
# ============================================================
@login_required
def list_video_plans(request):
    """List approved plans for the customer."""
    plans = GeneratedVideoPlan.objects.filter(user=request.user, status='approved')
    summary = [{
        "id": p.plan_id,
        "created_at": p.created_at.isoformat() + "Z" if p.created_at else "",
        "start_date": str(p.start_date),
        "end_date": str(p.end_date),
        "frequency": p.frequency,
        "post_count": p.video_posts.count(),
        "summary": p.summary[:200],
    } for p in plans]
    return JsonResponse({"plans": summary})


@login_required
def get_video_plan(request, plan_id):
    """Get a specific approved plan for viewing."""
    try:
        plan = GeneratedVideoPlan.objects.get(plan_id=plan_id, user=request.user, status='approved')
        return JsonResponse(plan.to_dict())
    except GeneratedVideoPlan.DoesNotExist:
        return JsonResponse({"error": "Plan not found"}, status=404)


# ============================================================
# BUFFER POSTING & FEEDBACK (Video)
# ============================================================

@login_required
@require_POST
def approve_video_post(request, post_id):
    """
    Approves a video post and sends it directly to Buffer.
    Similar to hub.views.approve_post but for videos.
    """
    post = get_object_or_404(GeneratedVideoPost, post_id=post_id, plan__user=request.user)
    profile = getattr(request.user, 'business_profile', None)
    
    if not profile or not profile.buffer_access_token:
        return JsonResponse({"error": "Buffer not connected. Please connect Buffer in the Photo Hub first."}, status=400)

    # Refresh token if needed
    refresh_buffer_token(profile)
    
    headers = {
        'Authorization': f'Bearer {profile.buffer_access_token}',
        'Content-Type': 'application/json'
    }
    
    channels = profile.buffer_channels or {}
    success_count = 0
    errors = []
    
    # Absolute URL for video (Buffer needs public URLs)
    video_url = post.video_url
    if video_url and not video_url.startswith('http'):
        video_url = request.build_absolute_uri(video_url)

    for platform in post.platforms:
        channel_id = channels.get(platform)
        if not channel_id:
            # Fallback for platform name matching
            channel_id = next((cid for p, cid in channels.items() if p.lower() in platform.lower()), None)
            
        if not channel_id:
            errors.append(f"No {platform} channel linked in Buffer.")
            continue

        metadata_block = ""
        if platform.lower() == 'instagram':
            metadata_block = 'metadata: { instagram: { type: reel, shouldShareToFeed: true } }'
            
        query = f"""
        mutation CreatePost($text: String!, $channelId: ChannelId!, $videoUrl: String!) {{
          createPost(input: {{
            text: $text,
            channelId: $channelId,
            schedulingType: automatic,
            mode: shareNow,
            {metadata_block}
            assets: {{
              videos: [
                {{ url: $videoUrl }}
              ]
            }}
          }}) {{
            ... on PostActionSuccess {{ post {{ id }} }}
            ... on MutationError {{ message }}
          }}
        }}
        """
        variables = {
            "text": post.caption,
            "channelId": channel_id,
            "videoUrl": video_url
        }

        payload = { 'query': query, 'variables': variables }
        
        try:
            response = requests.post('https://api.buffer.com', json=payload, headers=headers)
            if response.status_code != 200:
                errors.append(f"API Error for {platform}: {response.text}")
                continue
                
            data = response.json()
            if 'errors' in data:
                errors.append(f"GraphQL Error for {platform}: {str(data['errors'])}")
                continue
                
            if 'data' in data and data['data'].get('createPost', {}).get('message'):
                errors.append(f"Buffer Error for {platform}: {data['data']['createPost']['message']}")
                continue
                
            success_count += 1
        except requests.exceptions.RequestException as e:
            errors.append(f"Network Error for {platform}: {str(e)}")
            
    if errors:
        return JsonResponse({"error": " | ".join(errors)}, status=400)
    
    platforms_str = ", ".join(post.platforms[:success_count]) if success_count else ""
    return JsonResponse({
        "ok": True,
        "status": "published", 
        "count": success_count,
        "message": f"🎉 Video published to {platforms_str}! Check your social media."
    })


@login_required
@require_POST
def submit_video_feedback(request, post_id):
    """Saves user feedback for a video post."""
    post = get_object_or_404(GeneratedVideoPost, post_id=post_id, plan__user=request.user)
    try:
        data = json.loads(request.body)
        Feedback.objects.create(
            video_post=post,
            user=request.user,
            tags=data.get('tags', []),
            notes=data.get('notes', '')
        )
        return JsonResponse({"ok": True})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
@csrf_exempt
def delete_video_plan(request, plan_id):
    """Delete a plan (customer initiated)."""
    try:
        plan = GeneratedVideoPlan.objects.get(plan_id=plan_id, user=request.user)
        plan.delete()
        return JsonResponse({"ok": True})
    except GeneratedVideoPlan.DoesNotExist:
        return JsonResponse({"error": "Plan not found"}, status=404)