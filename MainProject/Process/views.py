from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class HelpPageView(LoginRequiredMixin, TemplateView):
    template_name = "help_center.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["user_role"] = getattr(self.request.user, "user_type", "User")
        return context