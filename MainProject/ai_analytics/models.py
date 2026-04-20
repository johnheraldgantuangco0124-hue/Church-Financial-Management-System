# MainProject/ai_analytics/models.py
from django.db import models
from django.conf import settings

class OptimizerRunLog(models.Model):
    church_id = models.IntegerField(db_index=True)

    mode = models.CharField(max_length=20)             # "Manual" / "Historical"
    reference_year = models.IntegerField(null=True, blank=True)
    timeframe = models.CharField(max_length=10)        # "monthly" / "yearly"

    pool_used_monthly = models.DecimalField(max_digits=14, decimal_places=2)

    priorities_used = models.JSONField(default=dict)
    allocations_result = models.JSONField(default=dict)
    ministry_constraints = models.JSONField(default=dict)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["church_id", "created_at"]),
            models.Index(fields=["church_id", "reference_year"]),
        ]