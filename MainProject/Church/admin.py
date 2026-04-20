from django.contrib import admin
from .models import Denomination, Church, ChurchApplication

@admin.register(Denomination)
class DenominationAdmin(admin.ModelAdmin):
    list_display = ('name','contact_email','created_at')
    search_fields = ('name',)

@admin.register(Church)
class ChurchAdmin(admin.ModelAdmin):
    list_display = ('name','denomination','municipality_or_city','province','created_at')
    list_filter = ('denomination',)
    search_fields = ('name',)

@admin.register(ChurchApplication)
class ChurchApplicationAdmin(admin.ModelAdmin):
    list_display = ('church','denomination','status','applied_at','decided_at','decided_by')
    list_filter = ('status','denomination')
    search_fields = ('church__name','denomination__name')
