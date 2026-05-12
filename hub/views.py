import json
import os
import re
import base64
import mimetypes
from datetime import datetime, timedelta, date
import urllib.parse
import hashlib
import secrets
from django.utils import timezone

import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import BusinessProfile, GeneratedPlan, GeneratedPost, PlanRequest, Feedback, VideoRequest

@login_required
def request_plan(request):
    """User clicks Generate — creates a PlanRequest instead of calling AI."""
    if request.method == 'POST':
        body = json.loads(request.body.decode('utf-8'))
        request_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        
        PlanRequest.objects.create(
            user=request.user,
            request_id=request_id,
            start_date=body.get('start_date'),
            end_date=body.get('end_date'),
            frequency=body.get('frequency', 'daily'),
            platforms=body.get('platforms', []),
            platform_counts=body.get('photo_counts', {}),
            extra_notes=body.get('notes', ''),
            status='pending'
        )
        return JsonResponse({"ok": True, "request_id": request_id, "message": "Plan requested. Admin will review within 24h."})
    return JsonResponse({"error": "Method not allowed"}, status=405)

@login_required
def plan_request_status(request):
    """Check status of pending requests (both image and video)."""
    # Combine both types of requests
    reqs = list(PlanRequest.objects.filter(user=request.user).exclude(status='approved'))
    vreqs = list(VideoRequest.objects.filter(user=request.user).exclude(status='approved'))
    
    combined = sorted(reqs + vreqs, key=lambda x: x.created_at, reverse=True)
    return JsonResponse({"requests": [r.to_dict() for r in combined]})

@login_required
@require_POST
def submit_feedback(request, post_id):
    """Submit user feedback on a post."""
    post = get_object_or_404(GeneratedPost, post_id=post_id, plan__user=request.user)
    body = json.loads(request.body.decode('utf-8'))
    
    Feedback.objects.create(
        post=post,
        user=request.user,
        tags=body.get('tags', []),
        notes=body.get('notes', '')
    )
    return JsonResponse({"ok": True, "message": "Feedback submitted. Admin will review."})

@login_required
@require_POST
def approve_post(request, post_id):
    """Approve a post and publish it to Buffer API."""
    post = get_object_or_404(GeneratedPost, post_id=post_id, plan__user=request.user)
    
    profile = getattr(request.user, 'business_profile', None)
    if not profile or not profile.buffer_access_token:
        return JsonResponse({"error": "Please connect your Buffer account first."}, status=400)
        
    # Check and refresh token if needed
    refresh_buffer_token(profile)
    
    buffer_token = profile.buffer_access_token
    buffer_channels = profile.buffer_channels
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {buffer_token}'
    }
    
    errors = []
    success_count = 0
    
    # Loop through all platforms requested for this post
    for platform in post.platforms:
        # Match our platform string (e.g. 'instagram') to Buffer's service string
        channel_id = buffer_channels.get(platform)
        if not channel_id:
            errors.append(f"No Buffer channel connected for {platform}.")
            continue
            
        # Construct the GraphQL query
        # Instagram requires metadata { instagram: { type: post, shouldShareToFeed: true } }
        metadata_block = ""
        if platform == 'instagram':
            metadata_block = "metadata: { instagram: { type: post, shouldShareToFeed: true } },"

        if post.image_url:
            # Ensure image_url is absolute so Buffer can download it
            abs_image_url = request.build_absolute_uri(post.image_url)
            
            query = f"""
            mutation CreatePost($text: String!, $channelId: ChannelId!, $imageUrl: String!) {{
              createPost(input: {{
                text: $text,
                channelId: $channelId,
                schedulingType: automatic,
                mode: shareNow,
                {metadata_block}
                assets: {{
                  images: [
                    {{ url: $imageUrl }}
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
                "imageUrl": abs_image_url
            }
        else:
            query = f"""
            mutation CreatePost($text: String!, $channelId: ChannelId!) {{
              createPost(input: {{
                text: $text,
                channelId: $channelId,
                schedulingType: automatic,
                mode: shareNow,
                {metadata_block}
              }}) {{
                ... on PostActionSuccess {{ post {{ id }} }}
                ... on MutationError {{ message }}
              }}
            }}
            """
            variables = {
                "text": post.caption,
                "channelId": channel_id
            }

        payload = {
            'query': query,
            'variables': variables
        }
        
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
        "message": f"🎉 Post published to {platforms_str}! Check your social media."
    })

def generate_pkce_pair():
    """Generates a PKCE code verifier and code challenge."""
    # Verifier: random string
    verifier = secrets.token_urlsafe(64)
    # Challenge: SHA256 hash of verifier, base64url encoded
    challenge_hash = hashlib.sha256(verifier.encode('ascii')).digest()
    challenge = base64.urlsafe_b64encode(challenge_hash).decode('ascii').replace('=', '')
    return verifier, challenge
#6__4srUENGIIkhJDoY4k1pX9P8yCAaAmldhll9aJNmx
@login_required
def buffer_auth(request):
    """Redirect user to Buffer OAuth authorization page using PKCE."""
    client_id = "s04N2vp6llELftQFusMgLkhI14eRdnQcak0Pr3ccwTz"
    redirect_uri = "https://delana-fruited-tripp.ngrok-free.dev/hub/buffer/callback/"
    
    if not client_id:
        return HttpResponse("BUFFER_CLIENT_ID not configured in environment.", status=500)
    
    # PKCE step 1
    verifier, challenge = generate_pkce_pair()
    # Store verifier in session for Step 4
    request.session['buffer_code_verifier'] = verifier
        
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'posts:write posts:read account:read offline_access',
        'state': secrets.token_urlsafe(16),
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
        'prompt': 'consent'
    }
    
    auth_url = f"https://auth.buffer.com/auth?{urllib.parse.urlencode(params)}"
    return redirect(auth_url)

@login_required
def buffer_callback(request):
    """Handle Buffer OAuth callback using PKCE and fetch channels."""
    code = request.GET.get('code')
    state = request.GET.get('state') # In a production app, verify this state
    error = request.GET.get('error')

    if error:
        return HttpResponse(f"Buffer Authorization Error: {error}", status=403)

    client_id = "s04N2vp6llELftQFusMgLkhI14eRdnQcak0Pr3ccwTz"
    client_secret = "_1UNiSNIySx-TuuxFgmJIgqFKNMrpqX6BoKMm9iR2xS"
    redirect_uri = "https://delana-fruited-tripp.ngrok-free.dev/hub/buffer/callback/"
    
    # Retrieve verifier from session
    code_verifier = request.session.get('buffer_code_verifier')
    if not code_verifier:
        return HttpResponse("DEBUG ERROR: PKCE verifier missing from session. Your browser might be blocking cookies or the session expired. Please try clicking Connect again.", status=400)

    # Exchange code for access token (PKCE flow — no client_secret needed)
    token_url = "https://auth.buffer.com/token"
    data = {
        'client_id': client_id,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
        'code_verifier': code_verifier
    }
    
    try:
        # Use ONLY the body for credentials as requested by Buffer's 'one mechanism' rule
        response = requests.post(token_url, data=data)
        if response.status_code != 200:
            return HttpResponse(f"DEBUG ERROR: Token Exchange Failed ({response.status_code}). Buffer says: {response.text}. (Note: If you refreshed the page, this is normal. Try clicking Connect again.)", status=400)
            
        token_data = response.json()
        print("BUFFER TOKEN EXCHANGE RESPONSE:", token_data) # DEBUG LOG
        
        access_token = token_data.get('access_token')
        refresh_token = token_data.get('refresh_token')
        expires_in = token_data.get('expires_in', 3600) # Default 1 hour
        
        if not access_token:
            return HttpResponse("Failed to retrieve access token from Buffer.", status=400)
            
        # Fetch connected channels using the new GraphQL API
        graphql_url = "https://api.buffer.com"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        # Query to get organizations and their channels
        # We try to get channels from both account level and organization level
        query = """
        query {
          account {
            id
            email
            organizations {
              id
              name
              channels {
                id
                service
                name
              }
            }
          }
        }
        """
        
        try:
            graphql_response = requests.post(graphql_url, json={'query': query}, headers=headers)
            graphql_response.raise_for_status()
            graphql_data = graphql_response.json()
            
            # DEBUG: Print this to your terminal so we can see the structure
            print("BUFFER GRAPHQL RESPONSE:", graphql_data)
            
            if 'errors' in graphql_data:
                return HttpResponse(f"GraphQL Error fetching channels: {graphql_data['errors']}", status=400)
                
            # Build mapping of service -> channel_id
            channels = {}
            account_data = graphql_data.get('data', {}).get('account', {})
            organizations = account_data.get('organizations', [])
            
            for org in organizations:
                for channel in org.get('channels', []):
                    service = channel.get('service') # e.g., 'instagram', 'facebook'
                    if service:
                        channels[service] = channel.get('id')
            
            if not channels:
                 # If no channels found, show a more helpful message with the email
                 user_email = account_data.get('email', 'your account')
                 return HttpResponse(f"Connected successfully to Buffer account ({user_email}), but no social media channels were found. Please go to Buffer.com and connect your Instagram/Facebook account first, then come back here and click Connect again.", status=200)

            # Save to user's profile
            profile = getattr(request.user, 'business_profile', None)
            if not profile:
                profile = BusinessProfile(user=request.user)
                
            profile.buffer_access_token = access_token
            profile.buffer_refresh_token = refresh_token
            profile.buffer_token_expires_at = timezone.now() + timedelta(seconds=expires_in)
            profile.buffer_channels = channels
            profile.save()
            
            # Clear the verifier from session
            del request.session['buffer_code_verifier']
            
            return redirect('hub_plan')
            
        except requests.exceptions.RequestException as e:
            return HttpResponse(f"Error fetching channels from Buffer GraphQL: {e}", status=500)
            
    except requests.exceptions.RequestException as e:
        return HttpResponse(f"Error communicating with Buffer during token exchange: {e}", status=500)


def refresh_buffer_token(profile):
    """Refreshes the Buffer access token using the refresh token if expired."""
    if not profile.buffer_refresh_token:
        return
        
    # Check if token is expired or about to expire (within 5 mins)
    if profile.buffer_token_expires_at and profile.buffer_token_expires_at > timezone.now() + timedelta(minutes=5):
        return # Still valid
        
    client_id = "s04N2vp6llELftQFusMgLkhI14eRdnQcak0Pr3ccwTz"
    client_secret = "_1UNiSNIySx-TuuxFgmJIgqFKNMrpqX6BoKMm9iR2xS"
    
    token_url = "https://auth.buffer.com/token"
    data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'refresh_token',
        'refresh_token': profile.buffer_refresh_token
    }
    
    try:
        # Use ONLY the body for credentials
        response = requests.post(token_url, data=data)
        if response.status_code == 200:
            token_data = response.json()
            profile.buffer_access_token = token_data.get('access_token')
            # Buffer v2 might rotate refresh tokens, so update it if provided
            new_refresh = token_data.get('refresh_token')
            if new_refresh:
                profile.buffer_refresh_token = new_refresh
            
            expires_in = token_data.get('expires_in', 3600)
            profile.buffer_token_expires_at = timezone.now() + timedelta(seconds=expires_in)
            profile.save()
            print(f"Successfully refreshed Buffer token for {profile.user.email}")
        else:
            print(f"Failed to refresh Buffer token: {response.text}")
    except Exception as e:
        print(f"Error refreshing Buffer token: {e}")


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
    db_plans = GeneratedPlan.objects.filter(user=request.user, status='approved')
    plans = [p.to_dict() for p in db_plans]
    
    # Check connection status
    buffer_connected = bool(profile and profile.buffer_access_token)
    has_refresh_token = bool(profile and profile.buffer_refresh_token)

    return render(request, "hub/hub_plan.html", {
        "brand": brand,
        "plans": plans,
        "has_brand": brand is not None,
        "buffer_connected": buffer_connected,
        "has_refresh_token": has_refresh_token,
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
        "and conversion-focused. STRICTLY NO EMOJIS in any part of the output. You ALWAYS respond with valid JSON only — no prose, no markdown fences, "
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
4. Hashtags: 8–15 relevant ones, mix branded + niche + broad. STRICTLY NO EMOJIS in hashtags.
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