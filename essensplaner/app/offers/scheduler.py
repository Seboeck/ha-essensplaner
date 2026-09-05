"""Ein Job pro aktivierter Angebots-Quelle, Zeitplan aus OfferSourceConfig.
Läuft in-process im Add-on-Container (kein externer Cron nötig)."""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import database
from models import OfferSourceConfig
from offers.runner import run_source, get_or_create_source_config, CONNECTORS


def _job(source: str):
    from main import get_settings  # lazy Import, vermeidet Zirkularimport main<->scheduler
    db = database.SessionLocal()
    try:
        settings = get_settings(db)
        if not settings.plz:
            config = get_or_create_source_config(source, db)
            config.last_status = "Übersprungen: keine PLZ in den Einstellungen hinterlegt"
            db.commit()
            return
        store_url = {
            "kaufland_scraper": settings.kaufland_store_url,
            "edeka_scraper": settings.edeka_store_url,
        }.get(source)
        run_source(source, db, plz=settings.plz, store_url=store_url)
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    db = database.SessionLocal()
    try:
        for source in CONNECTORS:
            config = get_or_create_source_config(source, db)
            schedule_source(scheduler, config)
    finally:
        db.close()
    scheduler.start()
    return scheduler


def schedule_source(scheduler: BackgroundScheduler, config: OfferSourceConfig):
    job_id = f"offer_source_{config.source}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    if not config.enabled:
        return
    weekday = config.schedule_weekday if config.schedule_weekday is not None else 6
    hour = config.schedule_hour if config.schedule_hour is not None else 3
    scheduler.add_job(
        _job,
        trigger=CronTrigger(day_of_week=weekday, hour=hour),
        args=[config.source],
        id=job_id,
        replace_existing=True,
    )
