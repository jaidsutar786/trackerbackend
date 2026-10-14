# Notification Operations

## Production WebSockets

Install the backend requirements, including `channels-redis`, and set `REDIS_URL` in the backend environment to the Redis connection URL. The application selects the Redis channel layer when `REDIS_URL` is set; without it, Django uses the in-memory layer, which is for local development only and does not share messages across workers. When `DEBUG=False`, `python manage.py check` warns if the active channel layer is still in-memory.

Also configure `ALLOWED_HOSTS` for the application host and `CORS_ALLOWED_ORIGINS` for each frontend origin. Run the ASGI application through Daphne or another ASGI server in production.

## Notification Digest Schedule

The digest command sends unread notifications in batches of up to 25. The first run drains the existing unread backlog in batches; later runs continue from a per-user, per-frequency notification cursor. Failed recipients are logged and retried on a later run; a failure does not advance that user's cursor or stop delivery to other users.

Run a daily digest with:

```powershell
python manage.py send_notification_digests --frequency daily
```

Run a weekly digest with:

```powershell
python manage.py send_notification_digests --frequency weekly
```

Schedule these commands using the host's task scheduler. On Windows Task Scheduler, create a daily or weekly task whose program is the project's virtual-environment `python.exe`, whose arguments are `manage.py send_notification_digests --frequency daily` (or `weekly`), and whose **Start in** directory is `TrackerBackend`. On Linux, a crontab entry can use the same command and the absolute paths to the virtual-environment Python executable and `manage.py`.

Set `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and the other Django email settings before enabling digest preferences for users.