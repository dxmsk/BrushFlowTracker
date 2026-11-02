"""Runtime integration checks for configuration boundaries and bounded qB I/O."""
from collections import Counter
import copy
from threading import Event, Thread

from test_review_business import review_env, item, add, run_rss  # noqa: F401
from test_plugin_contract import plugin_module  # noqa: F401


def test_bulk_rss_uses_two_snapshots_for_one_hundred_pending_adds(review_env):
    env = review_env
    env.qb.confirm = False
    env.feed[:] = [item(env, f"batch-{i}", title=f"Batch Show S01E{i:03d} 2160p WEB-DL", seeders=5)
                   for i in range(1, 101)]
    result = run_rss(env)
    assert result["added"] == 100
    assert len(env.qb.added) == len(env.plugin._state["pending_managed"]) == 100
    assert env.qb.queries == 2, "One baseline and one fresh confirmation, not four queries per torrent"


def test_settings_publish_after_active_run_without_mixing_site_and_downloader(review_env, monkeypatch):
    env = review_env
    old = copy.deepcopy(env.plugin._config)
    old["downloader"] = "old-qb"
    env.plugin.init_plugin(old)
    entered, release = Event(), Event()
    connected, scanned, outcome = [], [], []

    def service(*_args, **_kwargs):
        connected.append(env.plugin._downloader)
        entered.set()
        assert release.wait(10)
        return env.service, None

    monkeypatch.setattr(env.plugin, "_qb_service", service)
    monkeypatch.setattr(env.plugin, "_scan_site", lambda site, *_a, **_k:
                        (scanned.append(site["id"]) or Counter()))
    worker = Thread(target=lambda: outcome.append(env.plugin.run_rss()), daemon=True)
    worker.start()
    try:
        assert entered.wait(5)
        changed = copy.deepcopy(old)
        changed["downloader"] = "new-qb"
        changed["sites"][0]["id"] = "new-site"
        response = env.plugin.save_settings(env.module.SettingsPayload(**changed))
        assert response.success
        assert response.data["settings"]["downloader"] == "new-qb"
        assert response.data["config_pending"] is True
        assert env.plugin._downloader == "old-qb"
        assert env.plugin._sites[0]["id"] == "a"
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive()
    assert len(outcome) == 1 and not outcome[0].get("error"), outcome
    assert connected == ["old-qb"] and scanned == ["a"]
    assert env.plugin._config["downloader"] == "new-qb"
    assert env.plugin._sites[0]["id"] == "new-site"
    assert env.plugin.get_status(include_tasks=False, include_downloaders=False).data["config_pending"] is False


def test_config_reload_keeps_live_state_container(review_env):
    env = review_env
    state, managed = env.plugin._state, env.plugin._state["managed"]
    changed = copy.deepcopy(env.plugin._config)
    changed["history_limit"] += 1
    env.plugin.save_settings(env.module.SettingsPayload(**changed))
    assert env.plugin._state is state
    assert env.plugin._state["managed"] is managed


def test_bulk_snapshot_tracks_successful_commands_without_refetch(review_env):
    from brushflowtracker.snapshots import BatchTorrentView
    env = review_env
    env.qb.publish("one", item(env, "one"))
    view = BatchTorrentView(env.qb)
    assert view.get_torrents()[0][0]["state"] == "downloading"
    assert view.pause_torrents(ids=["one"])
    assert view.get_torrents()[0][0]["state"] == "pausedDL"
    assert view.resume_torrents(ids=["one"])
    assert view.get_torrents()[0][0]["state"] == "downloading"
    assert view.delete_torrents(ids=["one"], delete_file=False)
    assert view.get_torrents()[0] == []
    assert env.qb.queries == 1


def test_explicit_readd_clears_tombstone_and_returns_to_task_view(review_env):
    env = review_env
    candidate = item(env, "again")
    add(env, "again", candidate)
    env.qb.delete_torrents(ids=["again"])
    env.plugin._archive_managed("again", "test cleanup")
    assert "again" in env.plugin._state["deleted_hashes"]
    add(env, "again", candidate)
    assert "again" not in env.plugin._state["deleted_hashes"]
    response = env.plugin.get_tasks("a")
    assert response.success
    assert [row["hash"] for row in response.data["tasks"]] == ["again"]


def test_failed_snapshot_remains_dirty_and_can_be_retried(plugin_module):
    from brushflowtracker.persistence import CoalescingWriter
    writer, calls = CoalescingWriter(), []

    def fail():
        calls.append("failed")
        raise RuntimeError("temporary storage failure")

    try:
        writer.save(fail)
    except RuntimeError:
        pass
    else:
        raise AssertionError("write must report its failure")
    assert writer.dirty
    assert writer.save(lambda: calls.append("saved"))
    assert not writer.dirty and calls == ["failed", "saved"]
