from apscheduler.schedulers.background import BackgroundScheduler
from models import OfferSourceConfig
from offers.scheduler import schedule_source


def test_schedule_source_adds_job_when_enabled():
    scheduler = BackgroundScheduler()
    scheduler.start()
    config = OfferSourceConfig(source="kaufland_scraper", enabled=True, schedule_weekday=6, schedule_hour=3)
    schedule_source(scheduler, config)
    assert scheduler.get_job("offer_source_kaufland_scraper") is not None
    scheduler.shutdown(wait=False)


def test_schedule_source_removes_job_when_disabled():
    scheduler = BackgroundScheduler()
    scheduler.start()
    config = OfferSourceConfig(source="kaufland_scraper", enabled=True, schedule_weekday=6, schedule_hour=3)
    schedule_source(scheduler, config)
    config.enabled = False
    schedule_source(scheduler, config)
    assert scheduler.get_job("offer_source_kaufland_scraper") is None
    scheduler.shutdown(wait=False)


def test_startup_wires_scheduler_with_jobs_for_all_sources(client):
    from main import app
    scheduler = app.state.scheduler
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {
        "offer_source_kaufland_scraper",
        "offer_source_edeka_scraper",
        "offer_source_marktguru",
    }
