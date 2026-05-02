from django.contrib.auth.backends import ModelBackend
from .models import HubUser


class EmailBackend(ModelBackend):
    """Authenticate using email instead of username."""
    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            user = HubUser.objects.get(email=username)
        except HubUser.DoesNotExist:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
