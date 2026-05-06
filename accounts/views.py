from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib import messages
from .models import User

def unified_login(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        user = authenticate(request, email=email, password=password)
        if user is not None:
            login(request, user)
            next_url = request.GET.get('next') or request.POST.get('next') or 'landing'
            return redirect(next_url)
        else:
            messages.error(request, "Invalid email or password.")
    return render(request, 'accounts/login.html')

def unified_register(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already exists.")
            return render(request, 'accounts/register.html')
            
        user = User.objects.create_user(username=username, email=email, password=password)
        login(request, user)
        return redirect('landing')
        
    return render(request, 'accounts/register.html')

def unified_logout(request):
    logout(request)
    return redirect('landing')
