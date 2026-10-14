from django.conf import settings
from django.core.checks import Tags, Warning, register


@register(Tags.security)
def check_production_channel_layer(app_configs, **kwargs):
    if settings.DEBUG:
        return []

    backend = settings.CHANNEL_LAYERS['default']['BACKEND']
    if backend == 'channels_redis.core.RedisChannelLayer':
        return []

    return [Warning(
        'Production is using the in-memory Channels layer.',
        hint='Set REDIS_URL to a shared Redis instance for production WebSockets.',
        id='notifications.W001',
    )]