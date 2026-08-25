"""基于本地人体关键点的多帧行为风险规则引擎。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import acos, atan2, degrees, sqrt
from statistics import mean, pstdev
from zoneinfo import ZoneInfo

TRUNK_THRESHOLDS = (3.0, 5.0, 8.0)
GAIT_CV_THRESHOLDS = (5.0, 8.0, 12.0)
MIN_GAIT_STEPS = 10
LONG_SIT_SECONDS = 30 * 60
STAND_TRANSITION_SECONDS = 3
PACING_WINDOW_SECONDS = 5 * 60
EVENT_COOLDOWN_SECONDS = 60


@dataclass(slots=True)
class PoseSample:
    """单帧归一化关键点及采样时间，不进行持久化。"""

    timestamp: datetime
    points: dict[str, tuple[float, float, float]]


@dataclass(slots=True)
class BehaviorDetection:
    """规则引擎输出的可持久化行为事件。"""

    event_type: str
    severity: str
    confidence: float
    score: float
    evidence: dict[str, float | int | str]
    started_at: datetime
    ended_at: datetime


@dataclass(slots=True)
class BehaviorResult:
    """一次多帧分析更新的聚合结果。"""

    scores: dict[str, float] = field(default_factory=dict)
    events: list[BehaviorDetection] = field(default_factory=list)
    data_quality: dict[str, str | int | bool] = field(default_factory=dict)


def _distance(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    return sqrt((first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2)


def _midpoint(first: tuple[float, float, float], second: tuple[float, float, float]) -> tuple[float, float]:
    return ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)


def _joint_angle(
    first: tuple[float, float, float],
    vertex: tuple[float, float, float],
    third: tuple[float, float, float],
) -> float:
    vector_a = (first[0] - vertex[0], first[1] - vertex[1])
    vector_b = (third[0] - vertex[0], third[1] - vertex[1])
    length = sqrt(vector_a[0] ** 2 + vector_a[1] ** 2) * sqrt(vector_b[0] ** 2 + vector_b[1] ** 2)
    if length == 0:
        return 180.0
    cosine = max(-1.0, min(1.0, (vector_a[0] * vector_b[0] + vector_a[1] * vector_b[1]) / length))
    return degrees(acos(cosine))


def _severity(value: float, thresholds: tuple[float, float, float]) -> tuple[str, float]:
    if value >= thresholds[2]:
        return "high", 12.0
    if value >= thresholds[1]:
        return "medium", 8.0
    if value >= thresholds[0]:
        return "low", 4.0
    return "normal", 0.0


class BehaviorAnalyzer:
    """按会话维护短期关键点序列并输出解释性行为特征。"""

    def __init__(self, timezone_name: str = "Asia/Shanghai") -> None:
        self._timezone = ZoneInfo(timezone_name)
        self._centers: deque[tuple[datetime, float]] = deque()
        self._step_lengths: deque[float] = deque(maxlen=40)
        self._ankle_directions: deque[int] = deque(maxlen=3)
        self._boundary_contacts: deque[datetime] = deque()
        self._night_movements: deque[datetime] = deque()
        self._sit_started_at: datetime | None = None
        self._last_sitting_at: datetime | None = None
        self._last_events: dict[str, datetime] = {}
        self._last_center: tuple[datetime, float] | None = None

    def update(self, sample: PoseSample) -> BehaviorResult:
        """接收一个关键点样本并返回当前聚合特征和新事件。"""
        result = BehaviorResult()
        required = {"leftShoulder", "rightShoulder", "leftHip", "rightHip"}
        if not required.issubset(sample.points):
            result.data_quality = {"sufficient": False, "reason": "躯干关键点不足"}
            return result

        center_x = self._track_center(sample)
        self._detect_trunk(sample, result)
        self._detect_gait(sample, result)
        self._detect_sit_stand(sample, result)
        self._detect_pacing(sample, result)
        self._detect_night_activity(sample, center_x, result)
        self._detect_wall_support(sample, center_x, result)
        result.data_quality.setdefault("sufficient", True)
        result.data_quality["validSteps"] = len(self._step_lengths)
        if len(self._step_lengths) < MIN_GAIT_STEPS:
            result.data_quality["gait"] = "数据不足"
        return result

    def _track_center(self, sample: PoseSample) -> float:
        left_hip, right_hip = sample.points["leftHip"], sample.points["rightHip"]
        center_x = (left_hip[0] + right_hip[0]) / 2
        self._centers.append((sample.timestamp, center_x))
        cutoff = sample.timestamp - timedelta(seconds=PACING_WINDOW_SECONDS)
        while self._centers and self._centers[0][0] < cutoff:
            self._centers.popleft()
        return center_x

    def _detect_trunk(self, sample: PoseSample, result: BehaviorResult) -> None:
        shoulder = _midpoint(sample.points["leftShoulder"], sample.points["rightShoulder"])
        hip = _midpoint(sample.points["leftHip"], sample.points["rightHip"])
        angle = degrees(atan2(abs(shoulder[0] - hip[0]), max(abs(shoulder[1] - hip[1]), 1e-6)))
        severity, score = _severity(angle, TRUNK_THRESHOLDS)
        if score:
            result.scores["instability"] = score
            self._emit(result, "trunk_instability", severity, min(0.99, 0.65 + angle / 40), score, {"angleDeg": round(angle, 2)}, sample.timestamp)

    def _detect_gait(self, sample: PoseSample, result: BehaviorResult) -> None:
        if not {"leftAnkle", "rightAnkle"}.issubset(sample.points):
            return
        difference = sample.points["leftAnkle"][0] - sample.points["rightAnkle"][0]
        direction = 1 if difference >= 0 else -1
        self._ankle_directions.append(direction)
        if len(self._ankle_directions) >= 2 and self._ankle_directions[-1] != self._ankle_directions[-2]:
            length = abs(difference)
            if length >= 0.015:
                self._step_lengths.append(length)
        if len(self._step_lengths) < MIN_GAIT_STEPS:
            return
        average = mean(self._step_lengths)
        cv = pstdev(self._step_lengths) / average * 100 if average else 0.0
        severity, score = _severity(cv, GAIT_CV_THRESHOLDS)
        result.data_quality["stepLengthCvPct"] = f"{cv:.2f}"
        if score:
            result.scores["gait"] = score
            self._emit(result, "gait_variability", severity, 0.82, score, {"stepLengthCvPct": round(cv, 2), "steps": len(self._step_lengths)}, sample.timestamp)

    def _detect_sit_stand(self, sample: PoseSample, result: BehaviorResult) -> None:
        keys = {"leftHip", "rightHip", "leftKnee", "rightKnee", "leftAnkle", "rightAnkle"}
        if not keys.issubset(sample.points):
            return
        left_angle = _joint_angle(sample.points["leftHip"], sample.points["leftKnee"], sample.points["leftAnkle"])
        right_angle = _joint_angle(sample.points["rightHip"], sample.points["rightKnee"], sample.points["rightAnkle"])
        sitting = min(left_angle, right_angle) < 125
        if sitting:
            self._sit_started_at = self._sit_started_at or sample.timestamp
            self._last_sitting_at = sample.timestamp
            return
        if self._sit_started_at is None or self._last_sitting_at is None:
            return
        sitting_seconds = (self._last_sitting_at - self._sit_started_at).total_seconds()
        transition_seconds = (sample.timestamp - self._last_sitting_at).total_seconds()
        if sitting_seconds >= LONG_SIT_SECONDS and transition_seconds <= STAND_TRANSITION_SECONDS:
            result.scores["sit_stand"] = 10.0
            self._emit(result, "rapid_stand_after_sitting", "high", 0.85, 10.0, {"sittingSeconds": int(sitting_seconds), "transitionSeconds": round(transition_seconds, 2)}, sample.timestamp)
        self._sit_started_at = None
        self._last_sitting_at = None

    def _detect_wall_support(self, sample: PoseSample, center_x: float, result: BehaviorResult) -> None:
        wrists = [sample.points[key] for key in ("leftWrist", "rightWrist") if key in sample.points]
        moving = self._last_center is not None and abs(center_x - self._last_center[1]) >= 0.015
        if moving and any(wrist[0] <= 0.08 or wrist[0] >= 0.92 for wrist in wrists):
            self._boundary_contacts.append(sample.timestamp)
        cutoff = sample.timestamp - timedelta(seconds=10)
        while self._boundary_contacts and self._boundary_contacts[0] < cutoff:
            self._boundary_contacts.popleft()
        if len(self._boundary_contacts) >= 5:
            result.scores["wall_support"] = 6.0
            self._emit(result, "suspected_wall_support", "medium", 0.55, 6.0, {"boundaryFrames": len(self._boundary_contacts)}, sample.timestamp)
        self._last_center = (sample.timestamp, center_x)

    def _detect_pacing(self, sample: PoseSample, result: BehaviorResult) -> None:
        if len(self._centers) < 8:
            return
        directions: list[int] = []
        previous = self._centers[0][1]
        for _, current in list(self._centers)[1:]:
            delta = current - previous
            if abs(delta) >= 0.025:
                directions.append(1 if delta > 0 else -1)
                previous = current
        reversals = sum(1 for index in range(1, len(directions)) if directions[index] != directions[index - 1])
        if reversals >= 4:
            result.scores["pacing"] = 8.0
            self._emit(result, "pacing", "medium", 0.72, 8.0, {"directionReversals": reversals}, sample.timestamp)

    def _detect_night_activity(self, sample: PoseSample, center_x: float, result: BehaviorResult) -> None:
        local_time = sample.timestamp.replace(tzinfo=ZoneInfo("UTC")).astimezone(self._timezone) if sample.timestamp.tzinfo is None else sample.timestamp.astimezone(self._timezone)
        if local_time.hour not in {*range(22, 24), *range(0, 6)} or self._last_center is None:
            return
        if abs(center_x - self._last_center[1]) >= 0.02:
            self._night_movements.append(sample.timestamp)
        cutoff = sample.timestamp - timedelta(seconds=10)
        while self._night_movements and self._night_movements[0] < cutoff:
            self._night_movements.popleft()
        if len(self._night_movements) >= 3:
            result.scores["night"] = 8.0
            self._emit(result, "night_activity", "medium", 0.9, 8.0, {"localHour": local_time.hour, "movementFrames": len(self._night_movements)}, sample.timestamp)

    def _emit(
        self,
        result: BehaviorResult,
        event_type: str,
        severity: str,
        confidence: float,
        score: float,
        evidence: dict[str, float | int | str],
        timestamp: datetime,
    ) -> None:
        previous = self._last_events.get(event_type)
        if previous is not None and timestamp - previous < timedelta(seconds=EVENT_COOLDOWN_SECONDS):
            return
        self._last_events[event_type] = timestamp
        result.events.append(BehaviorDetection(event_type, severity, round(confidence, 2), score, evidence, timestamp, timestamp))
