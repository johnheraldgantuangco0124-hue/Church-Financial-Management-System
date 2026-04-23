from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views  # Needed for Logout

# Import views from the local views.py (Where HomeView likely lives)
from . import views
from .views import FrontPageView

urlpatterns = [
    # 1. Landing Page (Public)
    path('', FrontPageView.as_view(), name='landing'),

    # 2. Admin Interface
    path('admin/', admin.site.urls),

    # 3. App Includes
    path('Register/', include('Register.urls')),
    path('church/', include('Church.urls')),

    path("", include("Process.urls")),


    # =========================================================
    # MISSING PATHS (CRITICAL FOR REDIRECTS)
    # =========================================================

    # This is where users go after login/register
    path('1home/', views.HomeView.as_view(), name='home'),
    # This is required for the navbar "Logout" button
    path('logout/', auth_views.LogoutView.as_view(next_page='landing'), name='logout'),

    # =========================================================

    # Debugging / Testing
    path('test-welcome/', views.test_welcome_trigger, name='test_trigger'),

    path("", FrontPageView.as_view(), name="frontpage"),
    path("login/", FrontPageView.as_view(), name="login"),
]

# Media Files (Images) Support
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)