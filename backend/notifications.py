"""
backend/notifications.py
Handles email sending and notification dispatching for Heros AI platform.
Respects user notification preferences configured in the Setting model.
"""
import logging
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Sum, Count, Avg
from django.utils import timezone
from datetime import timedelta

from .models import User, Setting, ApiUsageTracking, BroadcastMessage

from django.utils.html import urlize, linebreaks

logger = logging.getLogger('hero_ai.views')

def render_email_html(subject, body_text):
    """
    Converts plain text email content into a styled HTML email.
    Automatically turns plain text URLs (e.g. https://...) into clickable HTML links.
    """
    formatted_content = linebreaks(urlize(body_text, autoescape=True))
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        a {{ color: #6366f1 !important; font-weight: 600; text-decoration: underline; }}
        a:hover {{ color: #4f46e5 !important; }}
    </style>
</head>
<body style="margin: 0; padding: 0; background-color: #0f172a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #e2e8f0;">
    <table align="center" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px; margin: 20px auto; background-color: #1e293b; border-radius: 12px; border: 1px solid #334155; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.5);">
        <!-- Header -->
        <tr>
            <td style="padding: 24px 30px; background: linear-gradient(135deg, #312e81 0%, #1e1b4b 100%); text-align: left; border-bottom: 1px solid rgba(255,255,255,0.1);">
                <h2 style="margin: 0; color: #ffffff; font-size: 20px; font-weight: 700; letter-spacing: -0.5px;">⚡ Heros AI</h2>
                <p style="margin: 4px 0 0 0; color: #a5b4fc; font-size: 13px;">Official Notification & Platform Update</p>
            </td>
        </tr>
        <!-- Content -->
        <tr>
            <td style="padding: 30px; font-size: 15px; line-height: 1.6; color: #cbd5e1;">
                <h3 style="margin-top: 0; color: #f8fafc; font-size: 18px; border-bottom: 1px solid #334155; padding-bottom: 10px;">{subject}</h3>
                <div style="margin-top: 15px; color: #e2e8f0; font-size: 14px; line-height: 1.7;">
                    {formatted_content}
                </div>
            </td>
        </tr>
        <!-- Footer -->
        <tr>
            <td style="padding: 20px 30px; background-color: #0f172a; border-top: 1px solid #334155; text-align: center; font-size: 12px; color: #64748b;">
                <p style="margin: 0 0 6px 0;">Sent with ❤️ by <strong>Heros AI Platform Engine</strong></p>
                <p style="margin: 0;">You received this message based on your Heros AI Developer notification settings.</p>
            </td>
        </tr>
    </table>
</body>
</html>"""
    return html


def get_target_users_for_audience(audience='product_updates'):
    """
    Returns QuerySet of users matching notification preference.
    """
    if audience == 'product_updates':
        return User.objects.filter(settings__notify_product_updates=True)
    elif audience == 'daily_usage':
        return User.objects.filter(settings__notify_daily_usage=True)
    elif audience == 'quota_alerts':
        return User.objects.filter(settings__notify_quota_alerts=True)
    elif audience == 'all':
        return User.objects.all()
    else:
        return User.objects.filter(settings__notify_product_updates=True)


def send_broadcast(subject, message_body, audience='product_updates', sender=None):
    """
    Dispatches a broadcast email to users matching the given audience selection.
    Creates a BroadcastMessage record in database for admin history.
    """
    users = get_target_users_for_audience(audience)
    recipient_emails = list(users.values_list('email', flat=True).distinct())

    sent_count = 0
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@heros.ai')
    html_body = render_email_html(subject, message_body)

    if recipient_emails:
        try:
            for email in recipient_emails:
                send_mail(
                    subject=subject,
                    message=message_body,
                    from_email=from_email,
                    recipient_list=[email],
                    html_message=html_body,
                    fail_silently=False
                )
                sent_count += 1
        except Exception as e:
            logger.error(f"Error sending broadcast emails: {e}")
            print(f"[EMAIL ERROR] Failed to send email to {recipient_emails}: {e}")
            raise e

    # Record history
    broadcast_log = BroadcastMessage.objects.create(
        sender=sender if isinstance(sender, User) else None,
        subject=subject,
        audience=audience,
        message_body=message_body,
        recipients_count=sent_count
    )

    return broadcast_log


def get_portal_url():
    """
    Returns the production/public portal URL for emails, avoiding localhost.
    """
    site_url = getattr(settings, 'SITE_URL', 'https://platform.heros.ai')
    if 'localhost' in site_url or '127.0.0.1' in site_url:
        site_url = getattr(settings, 'PUBLIC_SITE_URL', 'https://platform.heros.ai')
    return site_url.rstrip('/')


def send_daily_usage_summary():
    """
    Calculates 24-hour API usage for each user with notify_daily_usage=True
    and dispatches a summary digest.
    """
    users = get_target_users_for_audience('daily_usage')
    now = timezone.now()
    twenty_four_hours_ago = now - timedelta(hours=24)

    sent_count = 0
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@heros.ai')

    for user in users:
        usage = ApiUsageTracking.objects.filter(user=user, request_source='developer_api', timestamp__gte=twenty_four_hours_ago)
        totals = usage.aggregate(
            total_tokens=Sum('tokens_used'),
            total_reqs=Count('id'),
            avg_lat=Avg('latency_ms')
        )
        
        tokens = totals['total_tokens'] or 0
        reqs = totals['total_reqs'] or 0
        avg_latency = round(totals['avg_lat'] or 0, 1)

        portal_url = get_portal_url()
        subject = f"Heros AI - Your Daily API Usage Digest ({now.strftime('%b %d, %Y')})"
        body = (
            f"Hello {user.name},\n\n"
            f"Here is your daily usage summary for the past 24 hours:\n\n"
            f"• Total Requests: {reqs:,}\n"
            f"• Total Tokens Processed: {tokens:,}\n"
            f"• Average Latency: {avg_latency} ms\n\n"
            f"View detailed logs and API analytics on your Heros AI Developer Portal:\n{portal_url}/platform\n\n"
            f"— Heros AI Team\n"
            f"To adjust your notification preferences, visit your Developer Settings."
        )

        send_mail(
            subject=subject,
            message=body,
            from_email=from_email,
            recipient_list=[user.email],
            html_message=render_email_html(subject, body),
            fail_silently=True
        )
        sent_count += 1

    return sent_count


def send_quota_alert(user, usage_percentage):
    """
    Sends a warning email to a user when their token quota usage exceeds threshold.
    """
    try:
        setting = user.settings
        if not setting.notify_quota_alerts:
            return False
    except Setting.DoesNotExist:
        pass

    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@heros.ai')
    portal_url = get_portal_url()
    subject = f"⚠️ Heros AI Quota Alert: You have used {usage_percentage}% of your rate limit"
    body = (
        f"Hi {user.name},\n\n"
        f"Your Heros AI Developer account has crossed {usage_percentage}% of its allocated rate limit quota for this period.\n\n"
        f"To avoid disruption to your applications, please check your developer portal or upgrade your workspace tier.\n\n"
        f"Portal link: {portal_url}/platform\n\n"
        f"— Heros AI Infrastructure Team"
    )

    send_mail(
        subject=subject,
        message=body,
        from_email=from_email,
        recipient_list=[user.email],
        html_message=render_email_html(subject, body),
        fail_silently=True
    )
    return True

