from django.urls import path
from .views import HelpPageView

urlpatterns = [
    path("help/", HelpPageView.as_view(), name="help_center"),
]