"""The pairing relay passes messages between the devices in a room, and replays the latest."""

import json

from fastapi.testclient import TestClient

from lattice.lens.relay import create_app


def test_a_message_reaches_the_other_device_in_the_room_and_not_the_sender():
    client = TestClient(create_app())
    with client.websocket_connect("/ws/demo-1") as sim, \
            client.websocket_connect("/ws/demo-1") as tracer:
        sim.send_text(json.dumps({"type": "scene", "x": [1, 2]}))

        assert json.loads(tracer.receive_text()) == {"type": "scene", "x": [1, 2]}
        tracer.send_text(json.dumps({"type": "ablate", "nodes": ["h1_3"]}))
        assert json.loads(sim.receive_text())["nodes"] == ["h1_3"]


def test_a_device_joining_late_gets_the_latest_message_of_each_type():
    client = TestClient(create_app())
    with client.websocket_connect("/ws/room-2") as sim:
        sim.send_text(json.dumps({"type": "scene", "n": 1}))
        sim.send_text(json.dumps({"type": "scene", "n": 2}))
        sim.send_text(json.dumps({"type": "scenario", "name": "aml"}))
        with client.websocket_connect("/ws/room-2") as late:
            got = [json.loads(late.receive_text()) for _ in range(2)]

    assert {"type": "scene", "n": 2} in got and {"type": "scenario", "name": "aml"} in got


def test_rooms_are_separate():
    client = TestClient(create_app())
    with client.websocket_connect("/ws/aaa") as a, client.websocket_connect("/ws/bbb") as b:
        a.send_text(json.dumps({"type": "scene"}))
        b.send_text(json.dumps({"type": "ping"}))
        with client.websocket_connect("/ws/bbb") as b2:
            assert json.loads(b2.receive_text()) == {"type": "ping"}  # not a's scene
