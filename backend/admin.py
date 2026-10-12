from django.contrib import admin, messages
from django.db.models import Sum, Count, Avg
from django.utils import timezone
from datetime import timedelta

from .models import (
    User, Api, ChatSession, Chat, Setting, AnonymousUsage,
    DeveloperApiKey, ExternalProviderKeys, ApiUsageTracking, ActivityLog,
    BroadcastMessage
)
from .notifications import send_broadcast

# ─────────────────────────────────────────────────────────────────────────────
# Custom User Admin with Quick Security Actions
# ─────────────────────────────────────────────────────────────────────────────

@admin.action(description="⚠️ Revoke All Developer API Keys for Selected Users")
def revoke_all_api_keys(modeladmin, request, queryset):
    count = 0
    for user in queryset:
        keys = DeveloperApiKey.objects.filter(user=user, is_active=True)
        updated = keys.update(is_active=False)
        count += updated
        ActivityLog.objects.create(
            user=user,
            action="API_KEYS_REVOKED_BY_ADMIN",
            details=f"Admin revoked {updated} active API key(s)."
        )
    modeladmin.message_user(request, f"Successfully revoked {count} API key(s) across {queryset.count()} user(s).", messages.SUCCESS)

@admin.action(description="⭐ Upgrade Selected Users to Enterprise Developer Tier")
def upgrade_to_enterprise(modeladmin, request, queryset):
    updated_count = 0
    for user in queryset:
        setting, _ = Setting.objects.get_or_create(user=user)
        setting.user_role = "Enterprise Developer"
        setting.save()
        updated_count += 1
        ActivityLog.objects.create(
            user=user,
            action="UPGRADED_TO_ENTERPRISE",
            details="Admin upgraded user to Enterprise Developer tier."
        )
    modeladmin.message_user(request, f"Successfully upgraded {updated_count} user(s) to Enterprise tier.", messages.SUCCESS)

@admin.action(description="🚫 Ban Developer Account & Revoke Access")
def ban_developer_account(modeladmin, request, queryset):
    count = 0
    for user in queryset:
        DeveloperApiKey.objects.filter(user=user).update(is_active=False)
        ActivityLog.objects.create(
            user=user,
            action="ACCOUNT_BANNED_BY_ADMIN",
            details="Admin restricted developer account access."
        )
        count += 1
    modeladmin.message_user(request, f"Restricted account access and revoked keys for {count} user(s).", messages.WARNING)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'google_id', 'is_superuser', 'created_at')
    search_fields = ('name', 'email')
    list_filter = ('is_superuser', 'created_at')
    actions = [revoke_all_api_keys, upgrade_to_enterprise, ban_developer_account]


@admin.register(Api)
class ApiAdmin(admin.ModelAdmin):
    list_display = ('model_name', 'user', 'is_mandatory', 'updated_at')
    list_filter = ('model_name', 'is_mandatory')
    search_fields = ('user__email', 'model_name')


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'updated_at', 'created_at')
    search_fields = ('title', 'user__email')


@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ('task_type', 'model_used', 'user', 'timestamp')
    list_filter = ('task_type', 'model_used')
    search_fields = ('user__email', 'task_type', 'input_text')


@admin.register(Setting)
class SettingAdmin(admin.ModelAdmin):
    list_display = ('user', 'user_name', 'user_role', 'notify_daily_usage', 'notify_quota_alerts', 'notify_product_updates', 'updated_at')
    list_filter = ('notify_daily_usage', 'notify_quota_alerts', 'notify_product_updates', 'user_role')
    search_fields = ('user__email', 'user_name')


@admin.register(AnonymousUsage)
class AnonymousUsageAdmin(admin.ModelAdmin):
    list_display = ('user_key', 'message_count', 'updated_at')
    search_fields = ('user_key',)


@admin.register(DeveloperApiKey)
class DeveloperApiKeyAdmin(admin.ModelAdmin):
    list_display = ('name', 'scope', 'user', 'is_active', 'expires_at', 'last_used', 'created_at')
    list_filter = ('scope', 'is_active')
    search_fields = ('name', 'user__email', 'key')


@admin.register(ExternalProviderKeys)
class ExternalProviderKeysAdmin(admin.ModelAdmin):
    list_display = ('user', 'updated_at')
    search_fields = ('user__email',)


@admin.register(ApiUsageTracking)
class ApiUsageTrackingAdmin(admin.ModelAdmin):
    list_display = ('user', 'developer_key', 'model_used', 'request_source', 'tokens_used', 'latency_ms', 'estimated_cost', 'status_code', 'timestamp')
    list_filter = ('request_source', 'model_used', 'status_code')
    search_fields = ('user__email', 'model_used', 'endpoint')


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'user', 'ip_address', 'timestamp')
    list_filter = ('action',)
    search_fields = ('action', 'user__email', 'details')


from django.utils.html import format_html
from django.urls import reverse

@admin.register(BroadcastMessage)
class BroadcastMessageAdmin(admin.ModelAdmin):
    list_display = ('subject', 'audience', 'recipients_count', 'sender', 'created_at', 'delete_action')
    list_filter = ('audience', 'created_at')
    search_fields = ('subject', 'message_body')
    readonly_fields = ('recipients_count', 'created_at')
    actions = ['delete_selected']

    def delete_action(self, obj):
        delete_url = reverse('admin:backend_broadcastmessage_delete', args=[obj.id])
        return format_html(
            '<a class="btn btn-sm btn-outline-danger" href="{}" style="padding: 2px 8px; font-size: 0.75rem;"><i class="fas fa-trash-alt"></i> Delete</a>',
            delete_url
        )
    delete_action.short_description = 'Actions'
    delete_action.allow_tags = True

    def save_model(self, request, obj, form, change):
        if not change:
            sender_user = User.objects.filter(email=request.user.email).first() if request.user else None
            broadcast_log = send_broadcast(
                subject=obj.subject,
                message_body=obj.message_body,
                audience=obj.audience,
                sender=sender_user
            )
            obj.recipients_count = broadcast_log.recipients_count
            obj.sender = sender_user
            messages.success(request, f"🚀 Broadcast email successfully dispatched to {broadcast_log.recipients_count} user(s)!")
        super().save_model(request, obj, form, change)


# ─────────────────────────────────────────────────────────────────────────────
# Override Admin Site Index View to Inject Analytics Dashboard Context
# ─────────────────────────────────────────────────────────────────────────────

original_admin_index = admin.site.index

def custom_admin_index(request, extra_context=None):
    extra_context = extra_context or {}

    now = timezone.now()
    twenty_four_hours_ago = now - timedelta(hours=24)

    # Core Stats
    total_users = User.objects.count()
    active_users_24h = User.objects.filter(api_usage__request_source='developer_api', api_usage__timestamp__gte=twenty_four_hours_ago).distinct().count()
    
    usage_aggregates = ApiUsageTracking.objects.filter(request_source='developer_api').aggregate(
        total_tokens=Sum('tokens_used'),
        total_reqs=Count('id'),
        avg_lat=Avg('latency_ms')
    )
    
    usage_24h_aggregates = ApiUsageTracking.objects.filter(request_source='developer_api', timestamp__gte=twenty_four_hours_ago).aggregate(
        tokens_24h=Sum('tokens_used'),
        reqs_24h=Count('id')
    )

    total_tokens = usage_aggregates['total_tokens'] or 0
    total_requests = usage_aggregates['total_reqs'] or 0
    avg_latency = round(usage_aggregates['avg_lat'] or 0, 1)
    
    tokens_24h = usage_24h_aggregates['tokens_24h'] or 0
    reqs_24h = usage_24h_aggregates['reqs_24h'] or 0

    active_keys = DeveloperApiKey.objects.filter(is_active=True).count()

    # Subscriber Breakdown
    sub_product_updates = Setting.objects.filter(notify_product_updates=True).count()
    sub_daily_usage = Setting.objects.filter(notify_daily_usage=True).count()
    sub_quota_alerts = Setting.objects.filter(notify_quota_alerts=True).count()

    # Activity & Usage Feeds
    recent_activity_logs = ActivityLog.objects.select_related('user')[:8]
    recent_api_usage = ApiUsageTracking.objects.filter(request_source='developer_api').select_related('user', 'developer_key')[:8]
    recent_broadcasts = BroadcastMessage.objects.select_related('sender')[:5]

    extra_context.update({
        'kpi_total_users': total_users,
        'kpi_active_users_24h': active_users_24h,
        'kpi_total_tokens': total_tokens,
        'kpi_tokens_24h': tokens_24h,
        'kpi_total_requests': total_requests,
        'kpi_reqs_24h': reqs_24h,
        'kpi_avg_latency': avg_latency,
        'kpi_active_keys': active_keys,
        'sub_product_updates': sub_product_updates,
        'sub_daily_usage': sub_daily_usage,
        'sub_quota_alerts': sub_quota_alerts,
        'recent_activity_logs': recent_activity_logs,
        'recent_api_usage': recent_api_usage,
        'recent_broadcasts': recent_broadcasts,
    })

    return original_admin_index(request, extra_context=extra_context)

admin.site.index = custom_admin_index