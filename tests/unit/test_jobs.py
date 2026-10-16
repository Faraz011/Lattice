import pytest

from lattice.queue.jobs import JOB_TYPES, Job, Keys


def test_a_job_round_trips_through_stream_fields():
    job = Job.new("hypothesis", case_id="case_1", payload={"hypothesis": "fan_out"})

    restored = Job.from_fields(job.to_fields())

    assert restored == job


def test_new_jobs_get_distinct_ids_and_start_at_attempt_zero():
    a = Job.new("verify", case_id="case_1")
    b = Job.new("verify", case_id="case_1")

    assert a.job_id != b.job_id
    assert a.attempt == 0


def test_a_retry_keeps_the_job_id_and_counts_the_attempt():
    job = Job.new("investigate", case_id="case_1")

    retry = job.retried()

    assert retry.job_id == job.job_id
    assert retry.attempt == 1
    assert retry.payload == job.payload


def test_unknown_job_types_are_rejected():
    with pytest.raises(ValueError):
        Job.new("teleport", case_id="case_1")


def test_each_job_type_has_its_own_stream_in_the_namespace():
    keys = Keys("lattice")

    streams = {keys.stream(t) for t in JOB_TYPES}

    assert len(streams) == len(JOB_TYPES)
    assert all(s.startswith("lattice:jobs:") for s in streams)
    assert keys.dead_letter() == "lattice:jobs:dead"
    assert keys.events("case_9") == "lattice:events:case_9"
