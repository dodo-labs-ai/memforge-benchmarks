def _require_fsync(config):
    if not config.fsync:
        raise RuntimeError("fsync must stay on")


def install_stall_safeguards(app):
    app.add_startup_check(_require_fsync)
    app.add_watchdog("seconds_since_last_job_started", 300, "page_oncall")
