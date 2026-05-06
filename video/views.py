import json
import os
import re
import uuid
import requests
import tempfile
from datetime import datetime, timedelta, date

from moviepy import VideoFileClip, concatenate_videoclips

from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.core.files.storage import FileSystemStorage
from django.conf import settings
from django.contrib import messages

from hub.models import BusinessProfile, GeneratedPlan, GeneratedPost, PlanRequest, VideoRequest
from .models import VideoProfile, GeneratedVideoPlan, GeneratedVideoPost
from django.contrib.auth.decorators import login_required

# ============================================================
# VIDEO ONBOARDING — identical to hub_home
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
# VIDEO PLAN — dashboard (mirrors hub_plan)
# ============================================================
@login_required
def video_plan(request):
    """Main video studio dashboard — shows form + past plans."""
    if not hasattr(request.user, 'video_profile'):
        return redirect('video_onboarding')

    profile = request.user.video_profile
    brand = profile.to_brand_dict()
    db_plans = GeneratedVideoPlan.objects.filter(user=request.user)
    plans = [p.to_dict() for p in db_plans]
    plans_json = json.dumps(plans)

    return render(request, 'video/video_plan.html', {
        'brand': brand,
        'brand_obj': profile,
        'plans': plans,
        'plans_json': plans_json,
        'has_brand': True,
    })


# ============================================================
# HELPER — festival lookup (reuse hub's data)
# ============================================================
def _video_observances_in_range(start: date, end: date):
    out = []
    for ds, name in INDIAN_FESTIVALS_2026.items():
        try:
            d = datetime.strptime(ds, "%Y-%m-%d").date()
        except ValueError:
            continue
        if start <= d <= end:
            out.append({"date": ds, "name": name})

    cur = start
    while cur <= end:
        key = cur.strftime("%m-%d")
        if key in RECURRING_FINANCE_DAYS:
            ds = cur.strftime("%Y-%m-%d")
            if not any(o["date"] == ds for o in out):
                out.append({"date": ds, "name": RECURRING_FINANCE_DAYS[key]})
        cur += timedelta(days=1)

    out.sort(key=lambda x: x["date"])
    return out


@login_required
def request_video_plan(request):
    """User clicks Generate for video — creates a VideoRequest."""
    if request.method == 'POST':
        body = json.loads(request.body.decode('utf-8'))
        request_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        
        VideoRequest.objects.create(
            user=request.user,
            request_id=request_id,
            start_date=body.get('start_date'),
            end_date=body.get('end_date'),
            frequency=body.get('frequency', 'daily'),
            platforms=body.get('platforms', []),
            extra_notes=body.get('notes', ''),
            status='pending'
        )
        return JsonResponse({"ok": True, "request_id": request_id, "message": "Video plan requested. Admin will review."})
    return JsonResponse({"error": "Method not allowed"}, status=405)

@login_required
def video_request_status(request):
    """Check status of pending video requests."""
    reqs = VideoRequest.objects.filter(user=request.user).order_by('-created_at')
    return JsonResponse({"requests": [{"request_id": r.request_id, "status": r.status} for r in reqs]})

# ============================================================
# GENERATE VIDEO PLAN — POST endpoint (mirrors generate_plan)
# ============================================================
@login_required
@require_POST
@csrf_exempt
def generate_video_plan(request):
    """
    Accepts JSON body: {start_date, end_date, frequency, platforms, notes}
    Calls Claude to generate a date-by-date video content plan.
    Persists to DB and returns full plan JSON.
    """
    try:
        body = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    start_str = body.get("start_date")
    end_str = body.get("end_date")
    frequency = body.get("frequency", "daily")
    platforms = body.get("platforms") or ["instagram"]
    extra_notes = body.get("notes", "")

    if not start_str or not end_str:
        return JsonResponse({"error": "start_date and end_date are required"}, status=400)

    try:
        start_d = datetime.strptime(start_str, "%Y-%m-%d").date()
        end_d = datetime.strptime(end_str, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"error": "Dates must be YYYY-MM-DD"}, status=400)

    if end_d < start_d:
        return JsonResponse({"error": "end_date must be on/after start_date"}, status=400)

    if (end_d - start_d).days > 92:
        return JsonResponse({"error": "Range too large. Pick up to 90 days."}, status=400)

    profile = getattr(request.user, 'video_profile', None)
    if not profile:
        return JsonResponse({"error": "Complete video onboarding first."}, status=400)

    brand = profile.to_brand_dict()
    observances = _video_observances_in_range(start_d, end_d)
    total_days = (end_d - start_d).days + 1

    system_prompt = (
        "You are a senior video content strategist and AI video director for Indian brands. "
        "You produce date-anchored, platform-native video content plans — including cinematic prompts "
        "for Google Veo 3 AI video generator (4K output, native synchronized audio, 8-second clips), "
        "social captions, hooks, scripts, and hashtags. "
        "You ALWAYS respond with valid JSON only — no prose, no markdown fences, no commentary outside the JSON."
    )

    obs_block = ""
    if observances:
        obs_block = "FESTIVALS / NOTABLE DAYS in range (anchor a video on these):\n"
        for o in observances:
            obs_block += f"- {o['date']}: {o['name']}\n"
    else:
        obs_block = "FESTIVALS / NOTABLE DAYS in range: None — focus on educational + brand videos.\n"

    bp = brand
    sh = brand.get("social_handles", {})

    user_prompt = f"""
Build a complete, day-by-day VIDEO content plan for the brand below.

=== BRAND ===
Name: {bp.get('brand_name','')}
Industry: {bp.get('industry','')}
Target Audience: {bp.get('target_audience','')}
Goals: {bp.get('goals','')}
Video Style: {bp.get('video_style','')}
Tone: {bp.get('tone','')}
Brand Colors: {', '.join(bp.get('brand_colors', []))}
Preferred Duration: 30 seconds (3 segments of 10 seconds each)
Music Preference: {bp.get('music_preference','')}
Voiceover Required: {bp.get('voiceover', False)}
Active platforms: {', '.join([k for k,v in sh.items() if v])}

=== PLAN WINDOW ===
Start: {start_str}
End: {end_str}
Total days in range: {total_days}
Posting frequency: {frequency}
   - daily     => one video per day
   - alternate => every other day
   - weekly_3  => 3 videos per week (Mon/Wed/Fri)
   - weekly_2  => 2 videos per week (Tue/Fri)
Target platforms: {', '.join(platforms)}

Extra notes: {extra_notes or '(none)'}

{obs_block}

=== RULES ===
1. NEVER skip a festival/notable day — always anchor a video post on those dates.
2. Mix video types across the plan:
   - Festival / cultural moment (when applicable)
   - Educational / explainer (e.g., "5 tips for...") 
   - Product / promotional showcase
   - Brand story / testimonial
   - Engagement hook (trending reel format)
3. For each video post, write captions that are platform-native.
4. Hashtags: 8–15 relevant ones, mix branded + niche + broad.
5. The video_prompt MUST be a complete, self-contained prompt for a 30-second cinematic video.
   It MUST describe 3 sequential 10-second segments (Segment 1, Segment 2, Segment 3).
   Describe: scene setting, camera movement (pan, zoom, dolly, drone shot),
   subject action, lighting (golden hour, studio, neon), mood, color palette using
   brand colors {', '.join(bp.get('brand_colors', []))}, visual style ({bp.get('video_style','cinematic')}),
   any spoken dialogue or voiceover text for native audio synthesis,
   ambient sound design (music genre, sound effects), and any text overlays needed.
   Mention brand name "{bp.get('brand_name','')}" and tone "{bp.get('tone','')}".
   Include "ultra-detailed, cinematic, 4K, 30 seconds total (3 segments), professional" directives.
   Keep prompts 150–250 words.
6. The script field should be a short voiceover or on-screen text script (2–5 sentences max).
7. Each post object MUST follow this exact schema:
   {{
     "date": "YYYY-MM-DD",
     "day_of_week": "Monday",
     "occasion": "Diwali" or "Educational" or "Promotional" etc.,
     "post_type": "festival" | "educational" | "promotional" | "brand_story" | "engagement",
     "platforms": ["instagram", "youtube"],
     "title": "Short internal title",
     "script": "Voiceover or on-screen text script...",
     "caption": "Full social caption with line breaks as \\n",
     "hashtags": ["#BrandName", "#VideoMarketing", ...],
     "call_to_action": "Visit our website",
     "video_prompt": "Complete Google Veo 3 prompt...",
     "aspect_ratio": "9:16" | "16:9" | "1:1",
     "duration": "4" | "6" | "8",
     "color_palette_hint": ["#hex1", "#hex2"]
   }}

=== OUTPUT ===
Respond with a single JSON object (NOTHING else):
{{
  "summary": "2-3 sentence strategic summary of the video plan and storytelling arc",
  "themes": ["weekly theme 1", "weekly theme 2"],
  "posts": [ {{...post...}}, {{...post...}} ]
}}
""".strip()

    try:
        raw = _call_claude(system_prompt, user_prompt, max_tokens=16000, temperature=0.65)
    except requests.HTTPError as e:
        return JsonResponse({"error": f"AI provider error: {e.response.text[:300]}"}, status=502)
    except requests.RequestException as e:
        return JsonResponse({"error": f"Network error: {str(e)}"}, status=502)

    parsed = _extract_json_block(raw)
    if not parsed or "posts" not in parsed:
        return JsonResponse({
            "error": "Could not parse AI response. Try again.",
            "raw": raw[:1500],
        }, status=502)

    # Persist to DB
    plan_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")

    plan_record = GeneratedVideoPlan.objects.create(
        user=request.user,
        plan_id=plan_id,
        start_date=start_d,
        end_date=end_d,
        frequency=frequency,
        platforms=platforms,
        summary=parsed.get("summary", ""),
        themes=parsed.get("themes", [])
    )

    for i, p in enumerate(parsed.get("posts", [])):
        post_id = f"{plan_id}-{i}"
        GeneratedVideoPost.objects.create(
            plan=plan_record,
            post_id=post_id,
            sort_order=i,
            date=p.get("date", ""),
            day_of_week=p.get("day_of_week", ""),
            occasion=p.get("occasion", ""),
            post_type=p.get("post_type", ""),
            platforms=p.get("platforms", []),
            title=p.get("title", ""),
            script=p.get("script", ""),
            caption=p.get("caption", ""),
            hashtags=p.get("hashtags", []),
            call_to_action=p.get("call_to_action", ""),
            video_prompt=p.get("video_prompt", ""),
            aspect_ratio=p.get("aspect_ratio", "9:16"),
            duration=p.get("duration", "8"),
            color_palette_hint=p.get("color_palette_hint", []),
            video_url="",
            video_status="pending"
        )

    return JsonResponse(plan_record.to_dict())


# ============================================================
# GENERATE ACTUAL VIDEO for a specific post
# Uses Google Veo 3 — best quality, 15-second, native audio
# ============================================================
@login_required
@require_POST
@csrf_exempt
def generate_post_video(request):
    """
    Triggers Google Veo 3 video generation for a single post.
    Body: {plan_id, post_id, custom_prompt (optional)}
    """
    try:
        body = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    plan_id = body.get("plan_id")
    post_id = body.get("post_id")
    custom_prompt = body.get("custom_prompt")

    if not plan_id or not post_id:
        return JsonResponse({"error": "plan_id and post_id required"}, status=400)

    try:
        plan = GeneratedVideoPlan.objects.get(plan_id=plan_id, user=request.user)
    except GeneratedVideoPlan.DoesNotExist:
        return JsonResponse({"error": "Plan not found"}, status=404)

    try:
        post = plan.video_posts.get(post_id=post_id)
    except GeneratedVideoPost.DoesNotExist:
        return JsonResponse({"error": "Post not found"}, status=404)

    prompt = custom_prompt or post.video_prompt
    if not prompt:
        return JsonResponse({"error": "No video prompt available"}, status=400)

    # Determine aspect ratio — fall back to 9:16 for social/reels
    aspect_ratio = post.aspect_ratio if post.aspect_ratio in ("9:16", "16:9", "1:1") else "9:16"

    # Mark as processing immediately
    post.video_status = "processing"
    post.save()

    # -------------------------------------------------------
    # Call Minimax via AIML API
    # Model: minimax — High quality, 10-second segments
    # Endpoint: POST /v2/generate/video/minimax
    # -------------------------------------------------------
    api_url = "https://api.aimlapi.com/v2/generate/video/minimax"
    headers = {
        "Authorization": f"Bearer {AIML_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "minimax",
        "prompt": prompt,
        "duration": 10,
        "aspect_ratio": aspect_ratio,
    }

    try:
        task_ids = []
        for _ in range(3):
            api_res = requests.post(api_url, json=payload, headers=headers, timeout=60)
            api_data = api_res.json()
            
            # Veo 3 returns the task id under "id"; fall back to "generation_id" just in case
            task_id = api_data.get("id") or api_data.get("generation_id") or ""
            if task_id:
                task_ids.append(task_id)

        if not task_ids:
            post.video_status = "failed"
            post.save()
            return JsonResponse({"error": f"AIML did not return any task IDs. Raw response: {api_data}"}, status=500)

        post.sub_task_ids = task_ids
        post.generation_task_id = task_ids[0] # Legacy tracking field
        if custom_prompt:
            post.video_prompt = custom_prompt
        post.save()

    except Exception as e:
        post.video_status = "failed"
        post.save()
        return JsonResponse({"error": f"AIML API error: {str(e)}"}, status=502)

    return JsonResponse(post.to_dict())


# ============================================================
# POLL VIDEO STATUS for a specific post
# ============================================================
@login_required
def video_post_status(request, plan_id, post_id):
    """Frontend polls this to check if the video is ready."""
    try:
        plan = GeneratedVideoPlan.objects.get(plan_id=plan_id, user=request.user)
        post = plan.video_posts.get(post_id=post_id)
    except (GeneratedVideoPlan.DoesNotExist, GeneratedVideoPost.DoesNotExist):
        return JsonResponse({"error": "Not found"}, status=404)

    if post.video_status == "processing" and post.sub_task_ids:
        api_url = "https://api.aimlapi.com/v2/video/generations"
        headers = {"Authorization": f"Bearer {AIML_API_KEY}"}
        
        all_ready = True
        has_failed = False
        video_urls = []
        
        for t_id in post.sub_task_ids:
            try:
                res = requests.get(api_url, params={"generation_id": t_id}, headers=headers, timeout=30)
                if res.status_code == 200:
                    data = res.json()
                    api_status = data.get("status", "").lower()
                    
                    if api_status in ['completed', 'success', 'ready', 'finished']:
                        url = (
                            (data.get("video") or {}).get("url") or
                            data.get("file_url") or
                            data.get("video_url") or
                            (data.get("output") or {}).get("video_url") or
                            (data.get("output") or {}).get("url") or ""
                        )
                        if url:
                            video_urls.append(url)
                        else:
                            all_ready = False
                    elif api_status in ['failed', 'error']:
                        has_failed = True
                    else:
                        all_ready = False
                else:
                    all_ready = False
            except Exception:
                all_ready = False
                
        if has_failed:
            post.video_status = 'failed'
            post.save()
            return JsonResponse(post.to_dict())
            
        elif all_ready and len(video_urls) == len(post.sub_task_ids):
            # All clips are ready! Time to download and merge.
            import os
            try:
                temp_dir = tempfile.mkdtemp()
                clips = []
                for idx, v_url in enumerate(video_urls):
                    local_path = os.path.join(temp_dir, f"clip_{idx}.mp4")
                    r = requests.get(v_url, stream=True)
                    with open(local_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                    clips.append(VideoFileClip(local_path))
                
                final_clip = concatenate_videoclips(clips, method="compose")
                
                # Ensure media directory exists
                media_root = os.path.join(settings.BASE_DIR, 'media', 'videos')
                os.makedirs(media_root, exist_ok=True)
                
                output_filename = f"merged_{post.post_id.replace('-', '_')}.mp4"
                output_path = os.path.join(media_root, output_filename)
                
                # Write final merged video
                final_clip.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)
                
                # Cleanup clips
                for clip in clips:
                    clip.close()
                
                post.video_status = 'ready'
                post.is_merged = True
                post.video_url = f"{settings.MEDIA_URL}videos/{output_filename}"
                post.save()
            except Exception as e:
                post.video_status = 'failed'
                post.save()
                print(f"Error merging videos: {e}")

    return JsonResponse(post.to_dict())


# ============================================================
# LIST / GET / DELETE PLANS
# ============================================================
@login_required
def list_video_plans(request):
    plans = GeneratedVideoPlan.objects.filter(user=request.user)
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
    try:
        plan = GeneratedVideoPlan.objects.get(plan_id=plan_id, user=request.user)
        return JsonResponse(plan.to_dict())
    except GeneratedVideoPlan.DoesNotExist:
        return JsonResponse({"error": "Plan not found"}, status=404)


@login_required
@require_POST
@csrf_exempt
def delete_video_plan(request, plan_id):
    try:
        plan = GeneratedVideoPlan.objects.get(plan_id=plan_id, user=request.user)
        plan.delete()
        return JsonResponse({"ok": True})
    except GeneratedVideoPlan.DoesNotExist:
        return JsonResponse({"error": "Plan not found"}, status=404)