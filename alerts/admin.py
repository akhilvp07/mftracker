from django.contrib import admin
from .models import Alert

@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ['user', 'alert_type', 'severity', 'title', 'is_read', 'is_emailed', 'created_at']
    list_filter = ['alert_type', 'severity', 'is_read', 'is_emailed']
    search_fields = ['title', 'message', 'user__username']
    date_hierarchy = 'created_at'
