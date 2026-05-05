from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    """Unified user model for the entire platform."""
    email = models.EmailField(unique=True)
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return self.email
