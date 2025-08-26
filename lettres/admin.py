# lettres/admin.py
from django.contrib import admin
from .models import Destination, Lettre, Response, SystemSettings, UserProfile


@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = ('nom', 'telephone', 'email')
    list_filter = ('nom',)
    search_fields = ('nom', 'telephone', 'email')
    ordering = ('nom',)


@admin.register(Lettre)
class LettreAdmin(admin.ModelAdmin):
    list_display = ('subject', 'category', 'date', 'deadline', 'priority', 'statut', 'sent_to_all_destinations', 'get_destinations')
    list_filter = ('category', 'statut', 'priority', 'service', 'format', 'sent_to_all_destinations')
    search_fields = ('subject', 'description')
    list_editable = ('statut', 'priority')
    date_hierarchy = 'date'
    ordering = ('-date',)
    filter_horizontal = ('destinations',)

    def get_destinations(self, obj):
        if obj.sent_to_all_destinations:
            return "Toutes les destinations"
        return ", ".join([d.nom for d in obj.destinations.all()])
    get_destinations.short_description = 'Destinations'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related('destinations')

@admin.register(Response)
class ResponseAdmin(admin.ModelAdmin):
    list_display = ('lettre', 'destination', 'statut', 'date_reponse', 'temps_reponse')
    list_filter = ('statut', 'destination', 'lettre__category')
    search_fields = ('lettre__subject', 'destination__nom', 'commentaires')
    list_editable = ('statut', 'date_reponse', 'temps_reponse')
    ordering = ('-lettre__date',)
    autocomplete_fields = ('lettre', 'destination')

@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    list_display = ('user', 'email_notifications', 'reminder_frequency', 'escalation_time', 'archive_in_progress_after_year', 'archive_closed_after_month')
    list_filter = ('email_notifications', 'archive_in_progress_after_year', 'archive_closed_after_month')
    search_fields = ('user__username',)
    ordering = ('user',)

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'destination', 'service')
    list_filter = ('role', 'destination', 'service')
    search_fields = ('user__username', 'user__email')
    list_editable = ('role', 'destination', 'service')
    ordering = ('user',)

    autocomplete_fields = ('destination',)

