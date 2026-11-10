def install_stall_safeguards(app):
    app.add_watchdog("oldest_pending_job_age", 600, "log")
