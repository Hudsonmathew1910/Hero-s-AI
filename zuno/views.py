import json
import os
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from groq import Groq
from ytmusicapi import YTMusic
from backend.hero_model import Baymax

def get_groq_client(request):
    """Resolve the Groq API key dynamically from the database for the authenticated user."""
    from backend.models import User, Api
    from backend.encryption import decrypt_api_key

    # Strictly fetch from the logged-in user's database settings
    user_id = request.session.get('user_id')
    if not user_id:
        # Check X-Session-Id header (for extension requests)
        session_key_raw = request.headers.get('X-Session-Id')
        if session_key_raw:
            from django.contrib.sessions.backends.db import SessionStore
            for sk in session_key_raw.split(','):
                sk = sk.strip()
                if not sk: continue
                s = SessionStore(session_key=sk)
                user_id = s.get('user_id')
                if user_id:
                    break

    if user_id:
        try:
            user = User.objects.get(user_id=user_id)
            api_obj = Api.objects.filter(user=user, model_name='Groq').first()
            if api_obj:
                api_key = decrypt_api_key(api_obj.api_key_encrypted)
                if api_key:
                    return Groq(api_key=api_key)
        except Exception:
            pass

    return None


def index(request):
    """Render the Zuno AI Music Assistant frontend."""
    # Require authentication to view the Zuno page
    if not request.session.get('user_id'):
        return redirect('/')

    # Check if the user has a Groq API key configured
    groq_client = get_groq_client(request)
    context = {
        'groq_missing': groq_client is None,
    }
    return render(request, 'zuno/zuno.html', context)


@csrf_exempt
def process_audio(request):
    """Process voice transcription, extract intent via Groq, and execute."""
    if request.method != 'POST':
        return JsonResponse({"error": "Method not allowed"}, status=405)

    groq_client = get_groq_client(request)
    if not groq_client:
        return JsonResponse({
            "error": "⚠️ Please log in to Hero AI and add your Groq API Key to use Zuno.",
            "message": "🔑 **Groq API Key Missing**\n\nTo use Zuno, please configure your Groq API key in your Hero AI profile settings:\n1. Log in to your Hero AI account.\n2. Navigate to **Settings** / **API Keys**.\n3. Add your Groq API Key and save.",
            "details": ["Please log in and configure your Groq API key in your profile settings."]
        }, status=500)

    try:
        data = json.loads(request.body)
        text = data.get('text', '')

        if not text:
            return JsonResponse({"error": "No text provided"}, status=400)

        # 1. Intent Routing with Groq
        system_prompt = (
            "You are an AI music assistant. Extract the user's intent and query from the given text. "
            "You MUST respond with ONLY a strict JSON object (no markdown, no extra text) with two keys: "
            "'intent' and 'query'. "
            "'intent' MUST be either 'play_song' or 'search_artist'. "
            "'query' is the name of the song or artist. "
            "If the user wants to play a song, use 'play_song'. "
            "If the user wants to search for an artist or song details, use 'search_artist'.\n\n"
        ) + Baymax.HERO_AI_UNIVERSE

        models_to_try = [
            "llama-3.1-8b-instant",
            "llama-3.3-70b-versatile",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ]

        response_content = None
        errors = []
        for model_name in models_to_try:
            try:
                completion = groq_client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text}
                    ],
                    temperature=0,
                    response_format={"type": "json_object"}
                )
                response_content = completion.choices[0].message.content
                break  # Stop if successful
            except Exception as e:
                errors.append(f"{model_name}: {str(e)}")
                continue

        if not response_content:
            return JsonResponse({"error": "All models failed", "details": errors}, status=500)

        intent_data = json.loads(response_content)

        intent = intent_data.get("intent")
        query = intent_data.get("query")
        print(f"[Zuno] Status -> Intent: {intent} | Query: {query}")

        if not intent or not query:
            return JsonResponse({"error": "Failed to parse intent or query."}, status=500)

        source = data.get('source', '')

        # 2. Action Execution
        if intent == "play_song":
            try:
                import webbrowser
                ytmusic = YTMusic()
                results = ytmusic.search(query, filter="songs")

                if results and len(results) > 0:
                    video_id = results[0].get("videoId")
                    if video_id:
                        url = f"https://www.youtube.com/watch?v={video_id}"
                        return JsonResponse({
                            "status": "play_extension",
                            "url": url,
                            "intent": "play_song",
                            "message": f"Playing '{results[0].get('title', query)}' on YouTube."
                        })

                # Fallback if ytmusic fails to find a videoId
                fallback_url = f"https://www.youtube.com/results?search_query={query}+official+audio"
                return JsonResponse({
                    "status": "play_extension",
                    "url": fallback_url,
                    "intent": "play_song",
                    "message": f"Playing '{query}' on YouTube."
                })
            except Exception as e:
                return JsonResponse({"error": f"Failed to play on YouTube: {str(e)}"}, status=500)

        elif intent == "search_artist":
            try:
                ytmusic = YTMusic()
                results = ytmusic.search(query, filter="songs")

                # Extract top 5
                top_5 = []
                for item in results[:5]:
                    title = item.get("title", "Unknown Title")
                    artists = ", ".join([a.get("name", "")
                                        for a in item.get("artists", [])])
                    video_id = item.get("videoId", "")
                    top_5.append({
                        "title": title,
                        "artists": artists,
                        "videoId": video_id
                    })

                return JsonResponse({
                    "status": "success",
                    "intent": "search_artist",
                    "query": query,
                    "results": top_5
                })
            except Exception as e:
                return JsonResponse({"error": f"Failed to search YT Music: {str(e)}"}, status=500)

        else:
            return JsonResponse({"error": f"Unknown intent: {intent}"}, status=400)

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload"}, status=400)
    except Exception as e:
        return JsonResponse({"error": f"Internal server error: {str(e)}"}, status=500)
