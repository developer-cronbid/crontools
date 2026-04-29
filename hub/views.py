import json
import os
import requests
from django.shortcuts import render
from django.http import HttpResponse
from django.conf import settings
from django.core.files.storage import FileSystemStorage
# from openai import OpenAI

def hub_home(request):
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
            # Match description to image by index, default to empty string if missing
            desc = ref_descriptions[index] if index < len(ref_descriptions) else ""
            
            references_data.append({
                "url": img_url,
                "description": desc
            })

        # 3. Structure the Data Dictionary
        data = {
            "business_profile": {
                "name": request.POST.get('name', ''),
                "industry": request.POST.get('industry', ''),
                "website": request.POST.get('website', ''),
                "target_audience": request.POST.get('target_audience', ''),
                "goals": request.POST.get('goals', '')
            },
            "brand_assets": {
                "logo_url": logo_path,
                # getlist allows us to save multiple colors if they added them
                "brand_colors": request.POST.getlist('brand_colors'), 
                "references": references_data,
                "fonts": request.POST.get('fonts', ''),
                "tone_of_voice": request.POST.get('tone_of_voice', '')
            },
            "social_handles": {
                "instagram": request.POST.get('instagram', ''),
                "facebook": request.POST.get('facebook', ''),
                "x_twitter": request.POST.get('x_twitter', ''),
                "linkedin": request.POST.get('linkedin', ''),
                "discord": request.POST.get('discord', ''),
                "youtube": request.POST.get('youtube', ''),
                "tiktok": request.POST.get('tiktok', '')
            }
        }

        # 4. Save to JSON File
        json_dir = os.path.join(settings.BASE_DIR, 'data')
        os.makedirs(json_dir, exist_ok=True)
        json_path = os.path.join(json_dir, 'onboarding_data.json')

        existing_data = []
        if os.path.exists(json_path):
            with open(json_path, 'r') as f:
                try:
                    existing_data = json.load(f)
                except json.JSONDecodeError:
                    pass

        existing_data.append(data)

        with open(json_path, 'w') as f:
            json.dump(existing_data, f, indent=4)

        # 5. Return HTMX Success Message with premium UI
        return HttpResponse('''
            <div class="flex flex-col items-center justify-center p-12 bg-white rounded-2xl shadow-2xl border border-gray-100 animate-fade-in-up">
                <div class="w-20 h-20 bg-green-100 rounded-full flex items-center justify-center mb-6">
                    <svg class="w-10 h-10 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                    </svg>
                </div>
                <h3 class="text-3xl font-extrabold text-gray-900">Onboarding Complete!</h3>
                <p class="mt-3 text-gray-500 text-center max-w-md">Your business profile is set up. We've securely saved your brand assets and information.</p>
            </div>
        ''')

    # GET Request: Render the form
    return render(request, "hub/hub_home.html")

AIML_API_KEY = "6081d4afffd640d18ea529f1e4747f90"  
AIML_BASE_URL = "https://api.aimlapi.com/v1/chat/completions"  
AIML_MODEL = "anthropic/claude-opus-4-6"  


def hub_plan(request):
    return render(request, "hub/hub_plan.html")

import re # Make sure 're' is imported at the top of your file!

def generate_calendar(request):
    """HTMX endpoint to generate the AI strategy using Claude Opus 4-6."""
    if request.method != "POST":
        return HttpResponse("Invalid request")

    start_date = request.POST.get("start_date")
    end_date = request.POST.get("end_date")
    
    company_data = get_onboarding_context()
    profile = company_data.get("business_profile", {})
    brand = company_data.get("brand_assets", {})

    business_context = f"Industry: {profile.get('industry')}. Audience: {profile.get('target_audience')}. Tone: {brand.get('tone_of_voice')}."
    
    headers = {
        "Authorization": f"Bearer {AIML_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        # --- MODEL 1: Trend Discovery ---
        trend_payload = {
            "model": AIML_MODEL,
            "system": "You are a trend analyst.", 
            "messages": [
                {"role": "user", "content": f"What are the current viral formats and upcoming events for this industry: {profile.get('industry')}?"}
            ],
            "temperature": 0.7,
            "max_tokens": 1000
        }
        
        trend_response = requests.post(AIML_BASE_URL, headers=headers, json=trend_payload, timeout=60)
        if not trend_response.ok:
            return HttpResponse(f'<div class="text-red-500 p-4 border border-red-200 bg-red-50 rounded-lg">API Error (Trends) {trend_response.status_code}: {trend_response.text[:200]}</div>')
            
        trend_data = trend_response.json()
        if 'choices' in trend_data:
            trends = trend_data['choices'][0]['message']['content']
        elif 'content' in trend_data:
            trends = trend_data['content'][0]['text']
        else:
            trends = "General industry trends"

        # --- MODEL 2: Strategy Generation ---
        strategy_prompt = f"""
        Create a structured social media calendar from {start_date} to {end_date}.
        Business Context: {business_context}
        Trends to include: {trends}
        
        Return ONLY a valid JSON array of objects. Each object must have: 
        "date" (YYYY-MM-DD), "platform", "post_type" (Evergreen, Trending, Festival), "caption", "hashtags", "image_prompt".
        Keep it strictly to 3 posts as a sample for this generation.
        """

        strategy_payload = {
            "model": AIML_MODEL,
            "system": "You are an expert social media strategist. Output only a raw JSON array. Do not include markdown blocks.",
            "messages": [
                {"role": "user", "content": strategy_prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 2048
        }
        
        calendar_response = requests.post(AIML_BASE_URL, headers=headers, json=strategy_payload, timeout=120)
        if not calendar_response.ok:
            return HttpResponse(f'<div class="text-red-500 p-4 border border-red-200 bg-red-50 rounded-lg">API Error (Strategy) {calendar_response.status_code}: {calendar_response.text[:200]}</div>')
            
        calendar_data = calendar_response.json()
        
        if 'choices' in calendar_data:
            raw_text = calendar_data['choices'][0]['message']['content']
        elif 'content' in calendar_data:
            raw_text = calendar_data['content'][0]['text']
        else:
            return HttpResponse(f'<div class="text-red-500 p-4 border border-red-200 bg-red-50 rounded-lg">Unrecognized response format.</div>')

        # Safely extract the JSON array using regex
        match = re.search(r'\[.*\]', raw_text.strip(), re.DOTALL)
        if not match:
            return HttpResponse(f'<div class="text-red-500 p-4 border border-red-200 bg-red-50 rounded-lg"><strong>Parsing Error:</strong> AI generated conversational text without a JSON array.</div>')
            
        raw_json = match.group(0)
        parsed_json = json.loads(raw_json)
        
        # FIXED: Pass data cleanly via HTTP Headers to Alpine
        response = HttpResponse('<div class="text-green-600 p-4 border border-green-200 bg-green-50 rounded-lg shadow-sm">Strategy generated successfully!</div>')
        response["HX-Trigger"] = json.dumps({"update-calendar": parsed_json})
        return response

    except requests.exceptions.RequestException as e:
        return HttpResponse(f'<div class="text-red-500 p-4 border border-red-200 bg-red-50 rounded-lg"><strong>Network Error:</strong> {str(e)}</div>')
    except json.JSONDecodeError:
        return HttpResponse(f'<div class="text-red-500 p-4 border border-red-200 bg-red-50 rounded-lg"><strong>Parsing Error:</strong> AI returned invalid JSON syntax.</div>')
    except Exception as e:
        return HttpResponse(f'<div class="text-red-500 p-4 border border-red-200 bg-red-50 rounded-lg"><strong>System Error:</strong> {str(e)}</div>')