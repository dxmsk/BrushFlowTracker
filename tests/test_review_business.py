"""Offline acceptance regressions; failures on 1.1.23 are intentional.

Downloader/RSS/host storage and time are local substitutes; sockets are blocked.
Assertions describe safety and recovery, not a future state-machine class.
Recorded baseline 9648d7d: 40 collected; 36 failed, 4 passed (no xfail/skip).
The four controls cover successful finalization, completed-old protection,
rejected-add protection, and explicitly scoped cleanup.
"""

import copy
import hashlib
import json
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))
from test_plugin_contract import plugin_module  # noqa: E402,F401

NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
SITE = {"id": "a", "name": "Review site"}
RULE = {"id": "r", "name": "Review task", "enabled": True,
        "url": "https://review.invalid/rss", "promotion": "any"}
WAIT = 10  # Event/join failure bound, never a scheduling sleep.


class OfflineQB:
    """Fresh value snapshots, explicit acknowledgement, observable side effects."""

    def __init__(self):
        self.rows, self.spec = {}, {}
        self.added, self.deleted, self.paused, self.resumed = [], [], [], []
        self.confirm = self.add_ok = self.delete_ok = True
        self.queries = 0

    def publish(self, key, candidate, tag=RULE["name"], **fields):
        self.rows[key] = {
            "hash": key, "name": candidate["title"], "tags": tag,
            "progress": 0.2, "amount_left": 800, "size": candidate["size"],
            "total_size": candidate["size"], "state": "downloading",
            "num_seeds": 5, "num_complete": 5, "dlspeed": 0,
            "ratio": 10, "seeding_time": 86400, **fields,
        }

    def get_torrents(self, **_kwargs):
        self.queries += 1
        return copy.deepcopy(list(self.rows.values())), False

    def add_torrent(self, content, tag=""):
        self.added.append(content)
        if not self.add_ok:
            return False, []
        if not self.confirm:
            return True, []
        key, candidate = self.spec[content]
        self.publish(key, candidate, tag)
        return True, [key]

    def delete_torrents(self, ids, delete_file=False):
        self.deleted.append((list(ids), bool(delete_file)))
        if self.delete_ok:
            for key in ids:
                self.rows.pop(key, None)
        return self.delete_ok

    def pause_torrents(self, ids):
        self.paused.extend(ids)
        for key in ids:
            if key in self.rows:
                self.rows[key]["state"] = "pausedDL"
        return True

    def resume_torrents(self, ids):
        self.resumed.extend(ids)
        for key in ids:
            if key in self.rows:
                self.rows[key]["state"] = "downloading"
        return True


@pytest.fixture
def review_env(plugin_module, monkeypatch):
    clock = SimpleNamespace(now=NOW, tick=10000.0)

    class ClockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = clock.now.astimezone(tz)
            return value if tz is not None else value.replace(tzinfo=None)

    def offline(*_args, **_kwargs):
        pytest.fail("Review regressions must never open an external connection")

    monkeypatch.setattr(socket, "create_connection", offline)
    monkeypatch.setattr(socket.socket, "connect", offline)
    monkeypatch.setattr(socket.socket, "connect_ex", offline)
    monkeypatch.setattr(plugin_module, "datetime", ClockDateTime)
    # Replace only the plugin's clock reference, not Python's global time module.
    monkeypatch.setattr(plugin_module, "time", SimpleNamespace(
        monotonic=lambda: clock.tick, sleep=lambda _seconds: None,
    ))
    qb, feed, disk = OfflineQB(), [], {}
    service = SimpleNamespace(instance=qb)
    cls = plugin_module.BrushFlowTracker
    monkeypatch.setattr(cls, "_qb_service", lambda *_a, **_k: (service, None))
    monkeypatch.setattr(cls, "save_data", lambda _self, key, value:
                        disk.__setitem__(key, json.dumps(value)))
    monkeypatch.setattr(cls, "get_data", lambda _self, key:
                        json.loads(disk[key]) if key in disk else None)
    monkeypatch.setattr(plugin_module.RssHelper, "parse",
                        lambda *_a, **_k: copy.deepcopy(feed), raising=False)
    plugin = cls()
    plugin.init_plugin({"sites": [{**SITE, "rss_rules": [RULE]}]})
    return SimpleNamespace(plugin=plugin, module=plugin_module, qb=qb,
                           service=service, feed=feed, disk=disk, clock=clock)


def item(env, key, resolution="2160p", **fields):
    return env.module.normalize_item({
        "title": f"Example S01E01 {resolution} WEB-DL H265",
        "enclosure": f"https://review.invalid/{key}", "size": 1000, **fields,
    }, env.clock.now)


def add(env, key, candidate, rule=RULE):
    env.qb.spec[candidate["enclosure"]] = (key, candidate)
    assert env.plugin._add_item(SITE, rule, candidate, env.service)


def run_rss(env):
    result = env.plugin.run_rss()
    assert not result.get("error"), result
    assert not result.get("rule_errors"), result
    return result


def restart(env):
    env.plugin._save_state_safely("review_restart")
    config = copy.deepcopy(env.plugin._config)
    env.plugin = env.module.BrushFlowTracker()
    env.plugin.init_plugin(config)


def upgrade(env):
    add(env, "old", item(env, "old", "1080p"))
    add(env, "new", item(env, "new"))
    assert set(env.qb.rows) == {"old", "new"}
    assert env.qb.deleted == [], "Submitting an upgrade must not delete old data"


def expire_pending(env):
    assert env.plugin._state["pending_managed"], "Must exercise pending confirmation"
    for record in env.plugin._state["pending_managed"]:
        record["added_at"] = (env.clock.now - timedelta(days=1)).isoformat()
    env.plugin._reconcile_pending_managed(env.service, env.qb.get_torrents()[0])
    assert env.plugin._state["pending_managed"] == []


def stall(env, key):
    env.qb.rows[key].update(num_seeds=0, num_complete=0, dlspeed=0)
    env.plugin._state["dead_seed_watch"][key] = {
        "since": (env.clock.now - timedelta(hours=2)).isoformat(),
        "progress": env.qb.rows[key]["progress"],
    }


def read_tasks(env, endpoint):
    if endpoint == "status":
        response = env.plugin.get_status("a", include_tasks=True, include_downloaders=False)
    else:
        response = env.plugin.get_tasks("a", force=endpoint == "tasks-force")
    assert response.success and not response.data.get("downloader_error")
    return response.data["tasks"]


def cleanup_config(env, labels):
    config = copy.deepcopy(env.plugin._config)
    config["sites"][0]["cleanup_rules"] = [{
        "id": "clean", "name": "Review cleanup", "enabled": True,
        "labels": labels, "min_ratio": 0, "min_seed_hours": 0, "delete_files": True,
    }]
    response = env.plugin.save_settings(env.module.SettingsPayload(**config))
    assert response.success
    return response.data["settings"]["sites"][0]["cleanup_rules"][0]


def test_remake_years_remain_distinct_after_persistence(review_env):
    env = review_env
    for key, year in (("original", 2004), ("remake", 2020)):
        add(env, key, item(env, key, title=f"The.Grudge.{year}.2160p.WEB-DL"))
    restart(env)
    env.qb.rows["original"].update(progress=1, amount_left=0, state="uploading")
    env.plugin._deduplicate_managed_torrents(env.service)
    assert env.qb.deleted == [], "Completing the 2004 movie cannot delete its 2020 remake"
    records = env.plugin._state["managed"]
    assert records["original"]["media_key"] != records["remake"]["media_key"]


@pytest.mark.parametrize("weak_qb_name", [False, True], ids=["rss-name", "less-informative-qb-name"])
def test_subtitle_episode_identity_survives_json_reload(review_env, weak_qb_name):
    env, keys = review_env, {}
    for episode in (1, 2):
        key = f"e{episode}"
        candidate = item(env, key,
            title="Call.Me.By.Fire.S06.2026.2160p.WEB-DL.H265" + (".HDR" if episode == 1 else ""),
            subtitle=f"披荆斩棘 第{episode:02d}期 | 官方", description="本周更新，大小 4 GB")
        keys[key] = candidate["media_key"]
        add(env, key, candidate)
    assert keys["e1"] != keys["e2"], "The RSS fixture really denotes separate episodes"
    restart(env)
    if weak_qb_name:
        for row in env.qb.rows.values():
            row["name"] = "Call.Me.By.Fire.2160p.WEB-DL"
    env.qb.rows["e1"].update(progress=1, amount_left=0, state="uploading")
    env.plugin._deduplicate_managed_torrents(env.service)
    assert env.qb.deleted == [], "A completed episode must never authorize deleting another"
    assert {key: row["media_key"] for key, row in env.plugin._state["managed"].items()} == keys


INCOMPLETE = [
    pytest.param({"progress": .999999, "amount_left": 1000}, id="near-one-positive-bytes"),
    pytest.param({"progress": 1, "amount_left": 1}, id="one-positive-bytes"),
    pytest.param({"progress": 0, "amount_left": 0, "size": 0, "total_size": 0,
                  "state": "metaDL"}, id="metadata-only"),
    pytest.param({"progress": 1, "amount_left": 0, "state": "metaDL"}, id="metadata-veto"),
]


@pytest.mark.parametrize("snapshot", INCOMPLETE)
def test_incomplete_replacement_cannot_authorize_file_deletion(review_env, snapshot):
    env = review_env
    upgrade(env)
    env.qb.rows["new"].update(snapshot)
    env.plugin._finalize_replacements(env.service, env.qb.get_torrents()[0])
    assert env.qb.deleted == [], "Remaining bytes/metaDL veto completion, even at progress=1"
    assert set(env.qb.rows) == {"old", "new"}


@pytest.mark.parametrize("snapshot", INCOMPLETE)
def test_cleanup_cannot_misclassify_last_incomplete_copy(review_env, snapshot):
    env = review_env
    cleanup_config(env, [RULE["name"]])
    add(env, "only", item(env, "only"))
    env.qb.rows["only"].update(snapshot)
    result = env.plugin.run_cleanup()
    assert not result.get("error"), result
    assert env.qb.deleted == [] and "only" in env.qb.rows


def test_confirmed_complete_replacement_deletes_old_only_once(review_env):
    env = review_env
    upgrade(env)
    assert env.qb.rows["old"]["state"] == "pausedDL"
    env.qb.rows["new"].update(progress=1, amount_left=0, state="uploading")
    env.plugin._finalize_replacements(env.service, env.qb.get_torrents()[0])
    env.plugin._finalize_replacements(env.service, env.qb.get_torrents()[0])
    assert env.qb.deleted == [(["old"], True)]
    assert set(env.qb.rows) == set(env.plugin._state["managed"]) == {"new"}


def test_transient_delete_failure_remains_retryable(review_env):
    env = review_env
    upgrade(env)
    env.qb.rows["new"].update(progress=1, amount_left=0, state="uploading")
    env.qb.delete_ok = False
    env.plugin._finalize_replacements(env.service, env.qb.get_torrents()[0])
    assert "old" in env.qb.rows and "old" in env.plugin._state["managed"]
    env.qb.delete_ok = True
    env.plugin._finalize_replacements(env.service, env.qb.get_torrents()[0])
    assert env.qb.deleted == [(["old"], True), (["old"], True)]
    assert "old" not in env.qb.rows and "new" in env.qb.rows


def test_completed_old_copy_is_not_removed_by_upgrade(review_env):
    env = review_env
    add(env, "old", item(env, "old", "1080p"))
    env.qb.rows["old"].update(progress=1, amount_left=0, state="uploading")
    add(env, "new", item(env, "new"))
    env.qb.rows["new"].update(progress=1, amount_left=0, state="uploading")
    env.plugin._finalize_replacements(env.service, env.qb.get_torrents()[0])
    env.plugin._deduplicate_managed_torrents(env.service)
    assert env.qb.deleted == [] and set(env.qb.rows) == {"old", "new"}


def test_failed_add_keeps_old_download_running(review_env):
    env = review_env
    add(env, "old", item(env, "old", "1080p"))
    env.qb.add_ok = False
    assert not env.plugin._add_item(SITE, RULE, item(env, "new"), env.service)
    assert env.qb.deleted == [] and env.qb.paused == []
    assert env.qb.rows["old"]["state"] == "downloading"


def test_unconfirmed_candidate_can_really_be_submitted_again(review_env):
    env = review_env
    candidate = item(env, "retry")
    env.feed[:] = [candidate]
    env.qb.spec[candidate["enclosure"]] = ("retry", candidate)
    env.qb.confirm = False
    run_rss(env)
    expire_pending(env)
    url_key = hashlib.sha1(candidate["enclosure"].encode()).hexdigest()
    assert url_key not in env.plugin._state["processed_urls"]
    env.qb.confirm = True
    run_rss(env)  # Full RSS path, not _flush_pending_candidates bypassing dedup.
    assert env.qb.added == [candidate["enclosure"], candidate["enclosure"]]
    assert "retry" in env.qb.rows and "retry" in env.plugin._state["managed"]


def test_unconfirmed_upgrade_expiry_restores_only_old_download(review_env):
    env = review_env
    add(env, "old", item(env, "old", "1080p"))
    env.qb.confirm = False
    add(env, "new", item(env, "new"))
    expire_pending(env)
    assert env.qb.deleted == [] and set(env.qb.rows) == {"old"}
    assert env.qb.rows["old"]["state"] == "downloading"


def test_stalled_upgrade_recovers_old_without_deleting_incomplete_data(review_env):
    env = review_env
    upgrade(env)
    stall(env, "new")
    result = env.plugin.monitor_free_expiry()
    assert not result.get("error"), result
    assert env.qb.deleted == [] and "old" in env.qb.rows
    assert "old" in env.qb.resumed and env.qb.rows["old"]["state"] == "downloading"
    run_rss(env)
    assert any(row["state"] == "downloading" and row["num_seeds"] > 0
               for row in env.qb.rows.values()), "Next RSS must not re-pause every viable copy"


def test_known_seeders_do_not_turn_a_quality_upgrade_into_a_downgrade(review_env):
    env = review_env
    high, low = item(env, "high", seeders=5), item(env, "low", "720p", seeders=5)
    for key, candidate in (("high", high), ("low", low)):
        env.qb.spec[candidate["enclosure"]] = (key, candidate)
    env.feed[:] = [high]
    run_rss(env)
    env.feed[:] = [low]
    run_rss(env)
    assert env.qb.added == [high["enclosure"]], "Known live 2160p must outrank known live 720p"


def test_repeated_rss_never_leaves_every_incomplete_copy_paused(review_env):
    env = review_env
    high, low = item(env, "high", seeders=5), item(env, "low", "720p", seeders=5)
    for key, candidate in (("high", high), ("low", low)):
        env.qb.spec[candidate["enclosure"]] = (key, candidate)
    env.feed[:] = [high]
    run_rss(env)
    env.feed[:] = [low]
    run_rss(env)
    run_rss(env)
    assert env.qb.deleted == [], "No complete copy exists"
    assert any(row["state"] == "downloading" for row in env.qb.rows.values()), (
        "Selection changes must resume the winner rather than accumulate pauses"
    )


def test_same_feed_loser_remains_usable_when_only_copy_stalls(review_env):
    env = review_env
    high, low = item(env, "high"), item(env, "low", "1080p", seeders=5)
    # Equal known availability makes quality, not an unknown-seeder tie, decisive.
    high["seeders"] = 5
    for key, candidate in (("high", high), ("low", low)):
        env.qb.spec[candidate["enclosure"]] = (key, candidate)
    env.feed[:] = [high, low]
    run_rss(env)
    assert env.qb.added == [high["enclosure"]]
    env.feed[:] = []  # Recovery must use the saved alternative, not a fresh RSS.
    restart(env)
    stall(env, "high")
    result = env.plugin.monitor_free_expiry()
    assert not result.get("error"), result
    assert env.qb.deleted == [] and "high" in env.qb.rows
    assert low["enclosure"] in env.qb.added
    assert env.qb.rows["low"]["state"] == "downloading"


@pytest.mark.parametrize("endpoint", ["tasks", "tasks-force", "status"])
@pytest.mark.parametrize("observation", ["missing-pending", "visible-pending", "tag-only"])
def test_get_is_read_only_even_when_pending_or_recovery_would_match(review_env, endpoint, observation):
    env = review_env
    candidate = item(env, "observed")
    if observation != "tag-only":
        env.qb.confirm = False
        env.feed[:] = [candidate]
        run_rss(env)
    if observation != "missing-pending":
        env.qb.publish("observed", candidate)
    before = copy.deepcopy(env.plugin._state)
    actions = copy.deepcopy((env.qb.added, env.qb.deleted, env.qb.paused, env.qb.resumed))
    queries = env.qb.queries
    for _ in range(3):
        read_tasks(env, endpoint)
    assert env.qb.queries - queries == (3 if endpoint == "tasks-force" else 1)
    assert env.plugin._state == before, "GET must not consume confirmations or register managed tasks"
    assert (env.qb.added, env.qb.deleted, env.qb.paused, env.qb.resumed) == actions


@pytest.mark.parametrize("endpoint", ["tasks", "status"])
def test_cached_get_cannot_resurrect_a_deleted_task(review_env, endpoint):
    env = review_env
    cleanup_config(env, [RULE["name"]])
    add(env, "deleted", item(env, "deleted", free_until=NOW + timedelta(hours=1)))
    env.qb.rows["deleted"].update(progress=1, amount_left=0, state="uploading")
    assert {row["hash"] for row in read_tasks(env, endpoint)} == {"deleted"}
    result = env.plugin.run_cleanup()
    assert not result.get("error"), result
    assert "deleted" not in env.qb.rows and "deleted" not in env.plugin._state["managed"]
    before = copy.deepcopy(env.plugin._state)
    rows = read_tasks(env, endpoint)  # Clock unchanged: old UI cache has not expired.
    assert env.plugin._state == before, "A stale snapshot cannot undo deletion/archive"
    assert "deleted" not in {row["hash"] for row in rows}


@pytest.mark.parametrize("labels", [[], ["Removed RSS task"]], ids=["explicit-empty", "dangling-reference"])
def test_saving_cleanup_labels_cannot_expand_selection(review_env, labels):
    env = review_env
    saved = cleanup_config(env, labels)
    assert set(saved["labels"]).issubset(labels), "Empty/removed labels cannot become all RSS tasks"
    add(env, "unselected", item(env, "unselected"))
    env.qb.rows["unselected"].update(progress=1, amount_left=0, state="uploading")
    result = env.plugin.run_cleanup()
    assert not result.get("error"), result
    assert env.qb.deleted == [] and "unselected" in env.qb.rows


@pytest.mark.parametrize("tags", [RULE["name"], "unrelated", ""])
def test_explicit_empty_cleanup_labels_never_mean_match_all(plugin_module, tags):
    from brushflowtracker.core import first_cleanup_rule

    torrent = {"tags": tags, "ratio": 999, "seeding_time": 999999}
    rule = {"id": "empty", "enabled": True, "labels": [], "min_ratio": 0, "min_seed_hours": 0}
    assert first_cleanup_rule(torrent, [rule]) is None


def test_explicit_cleanup_label_still_matches_only_that_task(review_env):
    env = review_env
    cleanup_config(env, [RULE["name"]])
    add(env, "selected", item(env, "selected"))
    add(env, "other", item(env, "other", title="Another S01E02 2160p WEB-DL"),
        rule={"id": "other-rule", "name": "Other task"})
    for row in env.qb.rows.values():
        row.update(progress=1, amount_left=0, state="uploading")
    result = env.plugin.run_cleanup()
    assert not result.get("error"), result
    assert env.qb.deleted == [(["selected"], True)] and set(env.qb.rows) == {"other"}


def background(function):
    finished, outcome = Event(), []

    def execute():
        try:
            outcome.append(function())
        except BaseException as error:
            outcome.append(error)
        finally:
            finished.set()

    thread = Thread(target=execute, daemon=True)
    thread.start()
    return thread, finished, outcome


def assert_workers_finished(workers):
    for thread, finished, outcome in workers:
        assert not thread.is_alive() and finished.is_set(), "Test worker did not terminate"
        assert len(outcome) == 1 and not isinstance(outcome[0], BaseException), outcome
        if isinstance(outcome[0], dict):
            assert not outcome[0].get("error"), outcome


def test_expired_lease_cannot_start_overlapping_rss_while_owner_is_alive(review_env, monkeypatch):
    env = review_env
    entered, release, overlap = Event(), Event(), Event()
    candidate = item(env, "lease")
    env.qb.spec[candidate["enclosure"]] = ("lease", candidate)

    def parse(*_args, **_kwargs):
        if not entered.is_set():
            entered.set()
            if not release.wait(WAIT * 3):
                raise RuntimeError("Test did not release the first RSS read")
        elif not release.is_set():
            overlap.set()
        return [copy.deepcopy(candidate)]

    monkeypatch.setattr(env.module.RssHelper, "parse", parse)
    workers = [background(env.plugin.run_rss)]
    try:
        assert entered.wait(WAIT), "First worker never entered RSS"
        assert workers[0][0].is_alive()
        env.clock.tick += 100000  # Exceed the lease without sleeping or changing thread liveness.
        workers.append(background(env.plugin.run_rss))
        # A second run may skip immediately or serialize; neither may enter RSS now.
        workers[1][1].wait(WAIT)
    finally:
        release.set()
        for thread, _finished, _outcome in workers:
            thread.join(WAIT)
    assert_workers_finished(workers)
    assert not overlap.is_set(), "Lease expiry must not treat a live owner as a dead worker"
    assert env.qb.added == [candidate["enclosure"]]
    assert "lease" in env.plugin._state["managed"]


def test_json_snapshot_save_flushes_mutation_requested_while_writer_is_busy(review_env, monkeypatch):
    env = review_env
    captured, release = Event(), Event()
    writes = []

    def save_data(key, value):
        frozen = json.dumps(value)  # Serialize BEFORE blocking; no fixture reference aliasing.
        if not captured.is_set():
            captured.set()
            if not release.wait(WAIT * 3):
                raise RuntimeError("Test did not release the first JSON snapshot")
        env.disk[key] = frozen
        writes.append(json.loads(frozen))

    monkeypatch.setattr(env.plugin, "save_data", save_data)
    env.plugin._state["processed_urls"]["first"] = NOW.isoformat()
    workers = [background(lambda: env.plugin._save_state_safely("first"))]
    try:
        assert captured.wait(WAIT), "First writer never captured its JSON snapshot"
        env.plugin._state["processed_urls"]["second"] = NOW.isoformat()
        workers.append(background(lambda: env.plugin._save_state_safely("second")))
        # Accept dirty coalescing or blocking serialization, but never a dropped save.
        workers[1][1].wait(WAIT)
    finally:
        release.set()
        for thread, _finished, _outcome in workers:
            thread.join(WAIT)
    assert_workers_finished(workers)
    persisted = json.loads(env.disk[env.plugin.STATE_KEY])
    assert set(persisted["processed_urls"]) == {"first", "second"}, (
        "The completed writer must flush a save request made against its old snapshot"
    )
    assert len(writes) >= 2, "The first already-serialized snapshot cannot contain the second mutation"
