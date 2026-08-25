"""风险 PDF 与事件 CSV 报告生成服务。"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from flask import current_app
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import desc

from .extensions import db
from .models import Alert, BehaviorEvent, Elder, Intervention, RiskAssessment, now
from .services import DISCLAIMER

FONT_NAME = "AnbuChinese"


def _register_font() -> str:
    """注册可用中文字体，确保导出的 PDF 不出现方框。"""
    candidates = (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    )
    if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        font_path = next((item for item in candidates if item.is_file()), None)
        if font_path is None:
            raise RuntimeError("未找到可用于报告的中文字体")
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(font_path)))
    return FONT_NAME


def _local_time(value) -> str:
    if value is None:
        return "-"
    timezone = ZoneInfo(current_app.config["APP_TIMEZONE"])
    aware = value.replace(tzinfo=ZoneInfo("UTC")) if value.tzinfo is None else value
    return aware.astimezone(timezone).strftime("%Y-%m-%d %H:%M:%S")


def _styles() -> dict[str, ParagraphStyle]:
    font = _register_font()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontName=font, fontSize=22, leading=30, textColor=colors.HexColor("#0B5278"), alignment=TA_CENTER),
        "heading": ParagraphStyle("heading", parent=base["Heading2"], fontName=font, fontSize=14, leading=20, textColor=colors.HexColor("#0B5278"), spaceBefore=10, spaceAfter=8),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName=font, fontSize=9, leading=14, textColor=colors.HexColor("#263F4D")),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName=font, fontSize=7.5, leading=11, textColor=colors.HexColor("#5D7380")),
    }


def _table(rows: list[list[object]], widths: list[float] | None = None) -> Table:
    font = _register_font()
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B6E99")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B8CBD5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F8FB")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _trend_chart(assessments: list[RiskAssessment]) -> Drawing | None:
    recent = assessments[-20:]
    if len(recent) < 2:
        return None
    drawing = Drawing(170 * mm, 52 * mm)
    chart = LinePlot()
    chart.x = 18 * mm
    chart.y = 10 * mm
    chart.width = 142 * mm
    chart.height = 35 * mm
    chart.data = [[(index + 1, float(item.score or 0)) for index, item in enumerate(recent)]]
    chart.lines[0].strokeColor = colors.HexColor("#0B87B5")
    chart.lines[0].strokeWidth = 2
    chart.yValueAxis.valueMin = 0
    chart.yValueAxis.valueMax = 100
    chart.yValueAxis.valueStep = 20
    chart.yValueAxis.labels.fontName = _register_font()
    chart.xValueAxis.valueMin = 1
    chart.xValueAxis.valueMax = len(recent)
    chart.xValueAxis.valueStep = max(1, len(recent) // 5)
    chart.xValueAxis.labels.fontName = _register_font()
    drawing.add(chart)
    return drawing


def build_risk_pdf(elder_id: int, target: Path) -> Path:
    """生成包含趋势、场景、告警和干预闭环的风险 PDF。"""
    elder = db.session.get(Elder, elder_id)
    if elder is None:
        raise ValueError("老人档案不存在")
    assessments = db.session.query(RiskAssessment).filter_by(elder_id=elder_id).order_by(RiskAssessment.created_at).all()
    behavior_events = db.session.query(BehaviorEvent).filter_by(elder_id=elder_id).order_by(BehaviorEvent.created_at).all()
    alerts = db.session.query(Alert).filter_by(elder_id=elder_id).order_by(desc(Alert.created_at)).all()
    alert_ids = [item.id for item in alerts]
    interventions = db.session.query(Intervention).filter(Intervention.alert_id.in_(alert_ids)).order_by(desc(Intervention.created_at)).all() if alert_ids else []
    styles = _styles()
    target.parent.mkdir(parents=True, exist_ok=True)

    def footer(canvas, document) -> None:
        canvas.saveState()
        canvas.setFont(_register_font(), 8)
        canvas.setFillColor(colors.HexColor("#6A7F89"))
        canvas.drawString(18 * mm, 10 * mm, "安步守护 - 本地跌倒风险辅助报告")
        canvas.drawRightString(192 * mm, 10 * mm, f"第 {document.page} 页")
        canvas.restoreState()

    story: list = [
        Paragraph("安步守护风险与事件报告", styles["title"]),
        Spacer(1, 5 * mm),
        _table(
            [
                ["老人", "出生年份", "行动能力", "辅助器具", "隐私授权", "导出时间"],
                [elder.name, elder.birth_year or "-", elder.mobility_level, elder.assistive_device or "-", "已授权" if elder.consent_granted else "未授权", _local_time(now())],
            ],
            [24 * mm, 20 * mm, 26 * mm, 27 * mm, 22 * mm, 45 * mm],
        ),
        Spacer(1, 4 * mm),
        Paragraph(escape(DISCLAIMER), styles["small"]),
        Paragraph("风险趋势", styles["heading"]),
    ]
    chart = _trend_chart(assessments)
    story.append(chart or Paragraph("暂无足够风险评估记录，至少需要两次评估后显示趋势。", styles["body"]))
    latest = assessments[-1] if assessments else None
    feature_rows = [["领域", "得分"]]
    if latest:
        for key, label in (("individual", "个人与每日状态"), ("behavior", "行为"), ("environment", "环境"), ("time", "时间")):
            feature_rows.append([label, latest.features.get(key, 0)])
    else:
        feature_rows.append(["暂无评估", "-"])
    story.extend([Paragraph("最新四域评分", styles["heading"]), _table(feature_rows, [65 * mm, 30 * mm])])

    scene_counts = Counter(item.scene for item in assessments)
    risk_rows = [["场景", "评估次数", "最高分", "高风险次数"]]
    for scene in ("客厅", "卧室", "卫生间"):
        rows = [item for item in assessments if item.scene == scene]
        risk_rows.append([scene, scene_counts[scene], max((item.score or 0 for item in rows), default=0), sum(item.level == "high" for item in rows)])
    story.extend([Paragraph("场景统计", styles["heading"]), _table(risk_rows, [35 * mm, 35 * mm, 35 * mm, 35 * mm])])

    behavior_rows = [["时间", "场景", "行为", "严重度", "置信度"]]
    for item in behavior_events[-30:]:
        behavior_rows.append([_local_time(item.started_at), item.scene, item.event_type, item.severity, f"{item.confidence:.0%}"])
    if len(behavior_rows) == 1:
        behavior_rows.append(["-", "-", "暂无行为事件", "-", "-"])
    story.extend([Paragraph("行为风险事件", styles["heading"]), _table(behavior_rows, [38 * mm, 22 * mm, 46 * mm, 24 * mm, 23 * mm])])

    story.append(PageBreak())
    alert_rows = [["时间", "类型", "状态", "内容"]]
    for item in alerts[:30]:
        alert_rows.append([_local_time(item.created_at), item.kind, item.status, Paragraph(escape(item.message), styles["small"])])
    if len(alert_rows) == 1:
        alert_rows.append(["-", "-", "-", "暂无告警"])
    story.extend([Paragraph("告警历史", styles["heading"]), _table(alert_rows, [38 * mm, 24 * mm, 27 * mm, 75 * mm])])

    intervention_rows = [["时间", "告警编号", "操作", "说明"]]
    for item in interventions[:50]:
        intervention_rows.append([_local_time(item.created_at), str(item.alert_id), item.action, item.note or "-"])
    if len(intervention_rows) == 1:
        intervention_rows.append(["-", "-", "-", "暂无干预记录"])
    story.extend([Paragraph("干预记录", styles["heading"]), _table(intervention_rows, [38 * mm, 25 * mm, 36 * mm, 65 * mm])])

    document = SimpleDocTemplate(str(target), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm, title="安步守护风险报告", author="安步守护")
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return target


def build_events_csv(elder_id: int, target: Path) -> Path:
    """以统一行结构导出风险、行为、告警和干预明细。"""
    elder = db.session.get(Elder, elder_id)
    if elder is None:
        raise ValueError("老人档案不存在")
    target.parent.mkdir(parents=True, exist_ok=True)
    alerts = db.session.query(Alert).filter_by(elder_id=elder_id).all()
    alert_ids = [item.id for item in alerts]
    rows: list[list[object]] = []
    for item in db.session.query(RiskAssessment).filter_by(elder_id=elder_id).all():
        rows.append(["risk", item.id, _local_time(item.created_at), item.scene, item.level, item.score, "；".join(item.reasons)])
    for item in db.session.query(BehaviorEvent).filter_by(elder_id=elder_id).all():
        rows.append(["behavior", item.id, _local_time(item.started_at), item.scene, item.severity, item.score, item.event_type])
    for item in alerts:
        rows.append(["alert", item.id, _local_time(item.created_at), "-", item.status, "", item.message])
    if alert_ids:
        for item in db.session.query(Intervention).filter(Intervention.alert_id.in_(alert_ids)).all():
            rows.append(["intervention", item.id, _local_time(item.created_at), "-", item.action, "", item.note or ""])
    rows.sort(key=lambda row: str(row[2]))
    with target.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["recordType", "recordId", "timeAsiaShanghai", "scene", "statusOrLevel", "score", "detail"])
        writer.writerows(rows)
    return target
