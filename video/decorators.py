from django.shortcuts import redirect
from functools import wraps
from .models import VideoUser

def video_login_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if 'video_user_id' not in request.session:
            return redirect('video_login')
        try:
            request.video_user = VideoUser.objects.get(id=request.session['video_user_id'])
        except VideoUser.DoesNotExist:
            del request.session['video_user_id']
            return redirect('video_login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view
