from django.contrib.sessions.models import Session
from django.contrib.auth import get_user_model
from django.utils import timezone
User = get_user_model()
active_sessions = Session.objects.filter(expire_date__gte=timezone.now())
for s in active_sessions:
    data = s.get_decoded()
    user_id = data.get('_auth_user_id')
    if user_id:
        try:
            u = User.objects.get(pk=user_id)
            print(f"Session {s.session_key} belongs to {u.username} (Staff: {u.is_staff})")
        except User.DoesNotExist:
            print(f"Session {s.session_key} belongs to unknown user {user_id}")
