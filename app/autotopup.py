# Add this import + call inside start_scheduler():

from app.audit_stream import flush_now as flush_audit_stream

def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(auto_topup_tick, "interval",
                      seconds=settings.AUTO_TOPUP_INTERVAL_SECONDS,
                      id="auto_topup", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(reports_tick, "interval", seconds=3600,
                      id="reports", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(archive_tick, "interval", seconds=6 * 3600,
                      id="archive", replace_existing=True, max_instances=1, coalesce=True)
    if settings.AUDIT_STREAM_ENABLED:
        scheduler.add_job(flush_audit_stream, "interval", seconds=5,
                          id="audit_stream", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.start()
