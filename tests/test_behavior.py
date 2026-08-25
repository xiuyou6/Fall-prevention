"""多帧行为规则引擎测试。"""

from datetime import datetime, timedelta

from anbu.behavior import BehaviorAnalyzer, PoseSample


def sample(timestamp: datetime, **overrides) -> PoseSample:
    points = {
        "leftShoulder": (0.45, 0.2, 1.0),
        "rightShoulder": (0.55, 0.2, 1.0),
        "leftHip": (0.46, 0.55, 1.0),
        "rightHip": (0.54, 0.55, 1.0),
        "leftWrist": (0.4, 0.45, 1.0),
        "rightWrist": (0.6, 0.45, 1.0),
        "leftKnee": (0.46, 0.72, 1.0),
        "rightKnee": (0.54, 0.72, 1.0),
        "leftAnkle": (0.44, 0.92, 1.0),
        "rightAnkle": (0.56, 0.92, 1.0),
    }
    points.update(overrides)
    return PoseSample(timestamp, points)


def test_trunk_and_gait_rules_emit_explainable_events():
    analyzer = BehaviorAnalyzer()
    start = datetime(2026, 8, 25, 2, 0)
    events = []
    result = None
    for index in range(14):
        difference = 0.06 if index % 4 < 2 else 0.20
        direction = 1 if index % 2 == 0 else -1
        result = analyzer.update(
            sample(
                start + timedelta(seconds=index),
                leftShoulder=(0.68, 0.2, 1.0),
                rightShoulder=(0.78, 0.2, 1.0),
                leftAnkle=(0.5 + direction * difference / 2, 0.92, 1.0),
                rightAnkle=(0.5 - direction * difference / 2, 0.92, 1.0),
            )
        )
        events.extend(result.events)
    assert result is not None
    assert result.scores["gait"] >= 4
    assert result.data_quality["validSteps"] >= 10
    assert {item.event_type for item in events} >= {"trunk_instability", "gait_variability"}


def test_gait_is_marked_insufficient_before_ten_steps():
    result = BehaviorAnalyzer().update(sample(datetime(2026, 8, 25, 2, 0)))
    assert result.data_quality["gait"] == "数据不足"
    assert "gait" not in result.scores


def test_long_sitting_then_fast_standing_is_detected():
    analyzer = BehaviorAnalyzer()
    start = datetime(2026, 8, 25, 2, 0)
    sitting = {
        "leftHip": (0.4, 0.4, 1.0), "rightHip": (0.6, 0.4, 1.0),
        "leftKnee": (0.4, 0.6, 1.0), "rightKnee": (0.6, 0.6, 1.0),
        "leftAnkle": (0.6, 0.6, 1.0), "rightAnkle": (0.8, 0.6, 1.0),
    }
    analyzer.update(sample(start, **sitting))
    analyzer.update(sample(start + timedelta(minutes=30), **sitting))
    result = analyzer.update(sample(start + timedelta(minutes=30, seconds=2)))
    assert result.scores["sit_stand"] == 10
    assert result.events[0].event_type == "rapid_stand_after_sitting"


def test_night_movement_uses_asia_shanghai_time():
    analyzer = BehaviorAnalyzer("Asia/Shanghai")
    start = datetime(2026, 8, 25, 15, 0)  # 北京时间 23:00
    analyzer.update(sample(start))
    result = None
    for index, center in enumerate((0.60, 0.50, 0.62), start=1):
        result = analyzer.update(
            sample(
                start + timedelta(seconds=index * 2),
                leftHip=(center - 0.04, 0.55, 1.0),
                rightHip=(center + 0.04, 0.55, 1.0),
            )
        )
    assert result is not None
    assert result.scores["night"] == 8
    assert any(item.event_type == "night_activity" for item in result.events)
