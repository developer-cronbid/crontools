import json
import os
import re
import base64
import mimetypes
from datetime import datetime, timedelta, date

import requests
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import BusinessProfile, GeneratedPlan, GeneratedPost

# ============================================================
# AIML API CONFIG
# ============================================================
AIML_API_KEY = "1caa12b3cd1787b67fc7c2c6b60d065b"
AIML_CHAT_URL = "https://api.aimlapi.com/v1/chat/completions"
AIML_IMAGE_URL = "https://api.aimlapi.com/v1/images/generations"
AIML_TEXT_MODEL = "anthropic/claude-opus-4-6"
AIML_IMAGE_MODEL = "google/nano-banana-pro"

# ============================================================
# HUB HOME — requires login, saves to DB
# ============================================================
@login_required
def hub_home(request):
    # If user already completed onboarding, skip to plan
    if hasattr(request.user, 'business_profile'):
        return redirect('hub_plan')

    if request.method == 'POST':
        fs = FileSystemStorage()

        # 1. Handle Logo
        logo_path = ""
        logo_file = request.FILES.get('logo')
        if logo_file:
            filename = fs.save(f"onboarding_logos/{logo_file.name}", logo_file)
            logo_path = fs.url(filename)

        # 2. Handle Reference Images & Pair with Individual Descriptions
        ref_images = request.FILES.getlist('reference_images')
        ref_descriptions = request.POST.getlist('reference_descriptions')

        references_data = []
        for index, img in enumerate(ref_images):
            filename = fs.save(f"onboarding_references/{img.name}", img)
            img_url = fs.url(filename)
            desc = ref_descriptions[index] if index < len(ref_descriptions) else ""
            references_data.append({"url": img_url, "description": desc})

        # 3. Save to Database
        BusinessProfile.objects.create(
            user=request.user,
            business_name=request.POST.get('name', ''),
            industry=request.POST.get('industry', ''),
            website=request.POST.get('website', ''),
            target_audience=request.POST.get('target_audience', ''),
            goals=request.POST.get('goals', ''),
            logo_url=logo_path,
            brand_colors=request.POST.getlist('brand_colors'),
            references=references_data,
            fonts=request.POST.get('fonts', ''),
            tone_of_voice=request.POST.get('tone_of_voice', ''),
            instagram=request.POST.get('instagram', ''),
            facebook=request.POST.get('facebook', ''),
            x_twitter=request.POST.get('x_twitter', ''),
            linkedin=request.POST.get('linkedin', ''),
            discord=request.POST.get('discord', ''),
            youtube=request.POST.get('youtube', ''),
            tiktok=request.POST.get('tiktok', ''),
        )

        return redirect('hub_plan')

    return render(request, "hub/hub_home.html")


# ============================================================
# HELPERS
# ============================================================
def _load_brand_data():
    """Load the most recent onboarding entry (single user for now)."""
    json_path = os.path.join(settings.BASE_DIR, 'data', 'onboarding_data.json')
    if not os.path.exists(json_path):
        return None
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            return data[-1]
        return None
    except (json.JSONDecodeError, IOError):
        return None


def _load_plans():
    """Load all saved plans."""
    plans_path = os.path.join(settings.BASE_DIR, 'data', 'plans.json')
    if not os.path.exists(plans_path):
        return []
    try:
        with open(plans_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_plans(plans):
    """Persist plans list."""
    json_dir = os.path.join(settings.BASE_DIR, 'data')
    os.makedirs(json_dir, exist_ok=True)
    plans_path = os.path.join(json_dir, 'plans.json')
    with open(plans_path, 'w') as f:
        json.dump(plans, f, indent=4)


def _extract_json_block(text):
    """Pull the first valid JSON object/array from a Claude response."""
    if not text:
        return None
    # Remove markdown fences
    text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.IGNORECASE)
    text = re.sub(r'\s*```$', '', text.strip())

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find first { or [ and balanced match
    for opener, closer in [('[', ']'), ('{', '}')]:
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if esc:
                esc = False
                continue
            if ch == '\\':
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
    return None


def _call_claude(system_prompt, user_prompt, max_tokens=8000, temperature=0.7):
    """Call Claude via AIML API and return the text response."""
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
    data = r.json()
    return data["choices"][0]["message"]["content"]


def _call_image_gen(prompt, aspect_ratio="1:1", resolution="2K"):
    """Generate an image using Nano Banana Pro and return the URL."""
    headers = {
        "Authorization": f"Bearer {AIML_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": AIML_IMAGE_MODEL,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "num_images": 1,
    }
    r = requests.post(AIML_IMAGE_URL, headers=headers, json=payload, timeout=240)
    r.raise_for_status()
    data = r.json()
    items = data.get("data") or []
    if not items:
        return None
    return items[0].get("url")


# ============================================================
# OBSERVANCE / FESTIVAL DATABASE
# (Indian festivals + globally relevant days. Static dates are exact;
#  lunar/movable festivals carry approximate windows for Claude to anchor.)
# ============================================================
INDIAN_FESTIVALS_2026 = {
    "2026-01-01": "New Year's Day",
    "2026-01-14": "Makar Sankranti / Pongal",
    "2026-01-26": "Republic Day (India)",
    "2026-02-14": "Valentine's Day",
    "2026-02-15": "Maha Shivratri",
    "2026-03-03": "Holi",
    "2026-03-08": "International Women's Day",
    "2026-03-21": "Eid-ul-Fitr (approx)",
    "2026-03-30": "Ram Navami",
    "2026-03-31": "Mahavir Jayanti",
    "2026-04-01": "Financial Year Begins (India) — big finance moment",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Ambedkar Jayanti / Tamil New Year / Vishu / Baisakhi",
    "2026-04-22": "Earth Day",
    "2026-05-01": "Labour Day",
    "2026-05-10": "Mother's Day",
    "2026-05-27": "Eid-ul-Adha (Bakrid, approx)",
    "2026-06-21": "Father's Day / International Yoga Day",
    "2026-07-09": "Rath Yatra",
    "2026-08-15": "Independence Day (India)",
    "2026-08-26": "Janmashtami",
    "2026-09-04": "Ganesh Chaturthi",
    "2026-09-15": "Engineer's Day (India)",
    "2026-10-02": "Gandhi Jayanti",
    "2026-10-19": "Dussehra / Vijayadashami",
    "2026-10-25": "Karwa Chauth",
    "2026-11-08": "Diwali",
    "2026-11-09": "Govardhan Puja",
    "2026-11-10": "Bhai Dooj",
    "2026-11-17": "Chhath Puja",
    "2026-11-25": "Guru Nanak Jayanti",
    "2026-12-01": "World AIDS Day",
    "2026-12-25": "Christmas",
    "2026-12-31": "New Year's Eve",
}

# Recurring (every year, no year change)
RECURRING_FINANCE_DAYS = {
    "01-01": "New Year (financial resolutions trend)",
    "03-08": "International Women's Day",
    "04-01": "Start of Financial Year (India)",
    "04-22": "Earth Day",
    "07-01": "GST Day (India)",
    "10-30": "World Savings Day",
    "11-01": "World Vegan Day",
}


def _observances_in_range(start: date, end: date):
    """Return list of {date, name} for festivals/days in the range."""
    out = []
    for ds, name in INDIAN_FESTIVALS_2026.items():
        try:
            d = datetime.strptime(ds, "%Y-%m-%d").date()
        except ValueError:
            continue
        if start <= d <= end:
            out.append({"date": ds, "name": name})

    # Add recurring ones for any year in range
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


# ============================================================
# HUB PLAN — page render
# ============================================================
@login_required
def hub_plan(request):
    profile = getattr(request.user, 'business_profile', None)
    brand = profile.to_brand_dict() if profile else None
    db_plans = GeneratedPlan.objects.filter(user=request.user)
    plans = [p.to_dict() for p in db_plans]
    return render(request, "hub/hub_plan.html", {
        "brand": brand,
        "plans": plans,
        "has_brand": brand is not None,
    })


# ============================================================
# GENERATE PLAN — POST endpoint
# Returns JSON with the full schedule
# ============================================================
@require_POST
@csrf_exempt
def generate_plan(request):
    try:
        body = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    start_str = body.get("start_date")
    end_str = body.get("end_date")
    frequency = body.get("frequency", "daily")  # daily | alternate | weekly_3 | custom
    platforms = body.get("platforms") or ["instagram", "facebook"]
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
        return JsonResponse({"error": "Range too large. Please pick up to 90 days."}, status=400)

    # Load brand from authenticated user's DB profile
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Login required."}, status=401)
    profile = getattr(request.user, 'business_profile', None)
    if not profile:
        return JsonResponse({"error": "No brand data found. Complete onboarding first."}, status=400)
    brand = profile.to_brand_dict()

    observances = _observances_in_range(start_d, end_d)
    total_days = (end_d - start_d).days + 1

    # Compose a tight, machine-friendly system prompt
    system_prompt = (
        "You are a senior social media strategist and creative director for Indian SMB brands. "
        "You produce date-anchored social media plans that are culturally aware, platform-aware, "
        "and conversion-focused. You ALWAYS respond with valid JSON only — no prose, no markdown fences, "
        "no commentary outside the JSON."
    )

    references_block = ""
    refs = brand.get("brand_assets", {}).get("references", []) or []
    if refs:
        references_block = "PAST POST REFERENCES (study tone, layout, visual language):\n"
        for r in refs:
            references_block += f"- {r.get('description','(no description)')}  [image: {r.get('url','')}]\n"

    obs_block = ""
    if observances:
        obs_block = "FESTIVALS / NOTABLE DAYS in range (anchor a post on these):\n"
        for o in observances:
            obs_block += f"- {o['date']}: {o['name']}\n"
    else:
        obs_block = "FESTIVALS / NOTABLE DAYS in range: None highlighted — focus on educational + offer posts.\n"

    bp = brand.get("business_profile", {})
    ba = brand.get("brand_assets", {})
    sh = brand.get("social_handles", {})

    user_prompt = f"""
Build a complete, day-by-day social media plan for the brand below.

=== BRAND ===
Name: {bp.get('name','')}
Industry: {bp.get('industry','')}
Website: {bp.get('website','')}
Target audience: {bp.get('target_audience','')}
Goals: {bp.get('goals','')}

Brand colors: {', '.join(ba.get('brand_colors', []))}
Tone of voice: {ba.get('tone_of_voice','')}
Logo URL: {ba.get('logo_url','')}

Active social handles: {', '.join([k for k,v in sh.items() if v])}

{references_block}

=== PLAN WINDOW ===
Start: {start_str}
End: {end_str}
Total days in range: {total_days}
Posting frequency requested: {frequency}
   - daily       => one post per day
   - alternate   => every other day
   - weekly_3    => 3 posts per week (Mon/Wed/Fri)
   - weekly_2    => 2 posts per week (Tue/Fri)
Target platforms: {', '.join(platforms)}

Extra notes from user: {extra_notes or '(none)'}

{obs_block}

=== RULES ===
1. Pick post dates that respect the requested frequency. NEVER skip a festival/notable day in the
   range — always anchor a post on those dates even if it bends the frequency slightly.
2. Mix post types across the plan:
   - Festival / cultural moment (when applicable)
   - Educational / myth-buster (e.g., "Credit score myths")
   - Product / offer post (credit cards, loans, personalized offers)
   - Trust-building / testimonial-style
   - Engagement (poll, question, carousel hook)
3. For each post, write captions that are platform-native (Instagram = punchy + emojis + hashtags;
   LinkedIn = professional; Facebook = warm + direct). Keep captions under 600 characters unless
   it's clearly a long-form post.
4. Hashtags: 8–15 relevant ones, mix branded + niche + broad.
5. The image_prompt MUST be a complete, self-contained Nano Banana Pro prompt — describe scene,
   composition, subject, lighting, mood, colors (using the brand colors {', '.join(ba.get('brand_colors', []))}),
   style (photorealistic / 3D / illustration), aspect ratio intent, and any text overlay
   (specify EXACT text to be rendered on the image, in quotes). Mention the brand name "{bp.get('name','')}"
   and tone "{ba.get('tone_of_voice','')}". Include "ultra-detailed, sharp, HD, professional"
   directives. Keep prompts 60–120 words.
6. Each post object MUST follow this exact schema:
   {{
     "date": "YYYY-MM-DD",
     "day_of_week": "Monday",
     "occasion": "Diwali" or "Educational" or "Offer" etc.,
     "post_type": "festival" | "educational" | "offer" | "trust" | "engagement",
     "platforms": ["instagram", "facebook"],
     "title": "Short internal title for this post",
     "caption": "Full caption with line breaks as \\n",
     "hashtags": ["#FixRupee", "#CreditCard", ...],
     "call_to_action": "Apply now at fixrupee.com",
     "image_prompt": "complete Nano Banana Pro prompt...",
     "image_aspect_ratio": "1:1" | "4:5" | "9:16" | "16:9",
     "color_palette_hint": ["#10b7fe", "#ffffff"]
   }}

=== OUTPUT ===
Respond with a single JSON object of this shape (and NOTHING else):
{{
  "summary": "2–3 sentence strategic summary of the plan and the storytelling arc",
  "themes": ["weekly theme 1", "weekly theme 2", ...],
  "posts": [ {{...post...}}, {{...post...}}, ... ]
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

    # Stamp + persist to DB
    plan_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    
    plan_record = GeneratedPlan.objects.create(
        user=request.user,
        plan_id=plan_id,
        start_date=start_d,
        end_date=end_d,
        frequency=frequency,
        platforms=platforms,
        summary=parsed.get("summary", ""),
        themes=parsed.get("themes", [])
    )

    posts_data = parsed.get("posts", [])
    for i, p in enumerate(posts_data):
        post_id = f"{plan_id}-{i}"
        GeneratedPost.objects.create(
            plan=plan_record,
            post_id=post_id,
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
            color_palette_hint=p.get("color_palette_hint", []),
            image_url="",
            image_status="pending"
        )

    return JsonResponse(plan_record.to_dict())


# ============================================================
# GENERATE IMAGE for a specific post
# ============================================================
@require_POST
@csrf_exempt
def generate_post_image(request):
    try:
        body = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    plan_id = body.get("plan_id")
    post_id = body.get("post_id")
    custom_prompt = body.get("custom_prompt")  # optional override

    if not plan_id or not post_id:
        return JsonResponse({"error": "plan_id and post_id required"}, status=400)

    try:
        plan = GeneratedPlan.objects.get(plan_id=plan_id, user=request.user)
    except GeneratedPlan.DoesNotExist:
        return JsonResponse({"error": "Plan not found"}, status=404)

    try:
        post = plan.posts.get(post_id=post_id)
    except GeneratedPost.DoesNotExist:
        return JsonResponse({"error": "Post not found"}, status=404)

    prompt = custom_prompt or post.image_prompt
    if not prompt:
        return JsonResponse({"error": "No image prompt available"}, status=400)

    # Map aspect ratio
    ar = post.image_aspect_ratio or "1:1"
    valid_ar = {"21:9", "1:1", "4:3", "3:2", "2:3", "5:4", "3:4", "16:9", "9:16"}
    if ar not in valid_ar:
        ar = "1:1"

    try:
        img_url = _call_image_gen(prompt, aspect_ratio=ar, resolution="2K")
    except requests.HTTPError as e:
        post.image_status = "failed"
        post.save()
        return JsonResponse({"error": f"Image API error: {e.response.text[:300]}"}, status=502)
    except requests.RequestException as e:
        post.image_status = "failed"
        post.save()
        return JsonResponse({"error": f"Network error: {str(e)}"}, status=502)

    if not img_url:
        post.image_status = "failed"
        post.save()
        return JsonResponse({"error": "No image returned"}, status=502)

    post.image_url = img_url
    post.image_status = "ready"
    if custom_prompt:
        post.image_prompt = custom_prompt
    post.save()

    return JsonResponse({
        "post_id": post_id,
        "image_url": img_url,
        "image_prompt": prompt,
    })


# ============================================================
# LIST / GET / DELETE PLANS
# ============================================================
@login_required
def list_plans(request):
    plans = GeneratedPlan.objects.filter(user=request.user)
    # Lightweight list (without full posts payload)
    summary = [{
        "id": p.plan_id,
        "created_at": p.created_at.isoformat() + "Z" if p.created_at else "",
        "start_date": str(p.start_date),
        "end_date": str(p.end_date),
        "frequency": p.frequency,
        "post_count": p.posts.count(),
        "summary": p.summary[:200],
    } for p in plans]
    return JsonResponse({"plans": summary})


@login_required
def get_plan(request, plan_id):
    try:
        plan = GeneratedPlan.objects.get(plan_id=plan_id, user=request.user)
        return JsonResponse(plan.to_dict())
    except GeneratedPlan.DoesNotExist:
        return JsonResponse({"error": "Plan not found"}, status=404)


@login_required
@require_POST
@csrf_exempt
def delete_plan(request, plan_id):
    try:
        plan = GeneratedPlan.objects.get(plan_id=plan_id, user=request.user)
        plan.delete()
        return JsonResponse({"ok": True})
    except GeneratedPlan.DoesNotExist:
        return JsonResponse({"error": "Plan not found"}, status=404)