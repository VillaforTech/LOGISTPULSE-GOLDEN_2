import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from command_loop import consume_commands


class Consumer:
    def __init__(self, fail_commit=False):
        self.commits = []
        self.fail_commit = fail_commit
        self.closed = False
    def __iter__(self):
        return iter([SimpleNamespace(topic='orders', partition=0, offset=i) for i in (7, 8)])
    def commit(self, offsets):
        if self.fail_commit:
            self.fail_commit = False
            raise RuntimeError('commit unavailable')
        self.commits.append(next(iter(offsets.values())).offset)
    def close(self, autocommit):
        assert autocommit is False
        self.closed = True


def test_transient_failure_retries_before_next_message():
    consumer = Consumer()
    calls = []
    def process(message):
        calls.append(message.offset)
        if len(calls) == 1:
            assert consumer.commits == []
            raise RuntimeError('database unavailable')
    consume_commands(consumer, process, sleep=lambda _: None)
    assert calls == [7, 7, 8]
    assert consumer.commits == [8, 9]
    assert consumer.closed


def test_permanent_failure_never_advances_or_commits():
    consumer = Consumer()
    calls = []
    def process(message):
        calls.append(message.offset)
        raise RuntimeError('database unavailable')
    with pytest.raises(RuntimeError):
        consume_commands(consumer, process, sleep=lambda _: None)
    assert calls == [7] * 5
    assert consumer.commits == []
    assert consumer.closed


def test_commit_failure_replays_same_command():
    consumer = Consumer(fail_commit=True)
    calls = []
    consume_commands(consumer, lambda msg: calls.append(msg.offset), sleep=lambda _: None)
    assert calls == [7, 7, 8]
    assert consumer.commits == [8, 9]
