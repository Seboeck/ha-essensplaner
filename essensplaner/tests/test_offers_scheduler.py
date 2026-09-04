import threading

from apscheduler.schedulers.background import BackgroundScheduler
from models import OfferSourceConfig
from offers.scheduler import schedule_source


def _scheduler_thread_count() -> int:
    return sum(1 for t in threading.enumerate() if "APScheduler" in t.name)


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


def test_client_fixture_teardown_stops_scheduler_thread():
    """Regression test for the leaked-thread review finding: every `client`
    fixture use starts a live BackgroundScheduler via main.on_startup. Without
    a matching shutdown handler that stops app.state.scheduler, each test using
    `client` leaks a daemon thread that outlives the test (confirmed via
    threading.enumerate() to reach 18 leaked threads across the suite before
    the fix). Uses TestClient directly (not the `client` fixture) so the
    baseline thread count is captured deterministically regardless of test
    order or other fixtures already in use."""
    from fastapi.testclient import TestClient
    from main import app

    baseline = _scheduler_thread_count()

    with TestClient(app) as test_client:
        test_client.get("/api/recipes")
        assert _scheduler_thread_count() == baseline + 1

    assert _scheduler_thread_count() == baseline
