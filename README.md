# 安步守护

本地运行的老年人跌倒风险预防、前置干预和事件闭环系统。前端为 Vue 3，Flask 仅提供 JSON API、本地模型推理、SQLite 持久化、PDF/CSV 报告和 SMTP 通知。

## 功能边界

- 视频来源：浏览器默认摄像头（内置或系统默认 USB 摄像头）和本地 MP4/AVI/MOV/MKV 上传。
- 不支持：萤石云、RTSP、摄像头枚举和 USB 设备选择器。
- 账号角色：管理员、家属、老人。管理员管理账号和档案；家属仅管理已绑定老人；老人仅使用本人问询和安全响应。
- 风险结果仅作安全辅助提示，不构成医疗诊断。

## 本地启动

1. 安装后端依赖：`python -m pip install -r requirements-dev.txt`。
2. 安装前端依赖：`cd web && pnpm install`。
3. 复制 `.env.example` 为 `.env`，配置 `SECRET_KEY`、管理员密码和可选 SMTP。
4. 后端终端运行 `python app.py`，监听 `http://127.0.0.1:5000`。
5. 前端终端运行 `cd web && pnpm dev`，访问 `http://127.0.0.1:5173`。

开发模式初始管理员为 `admin / 123456`。当 `APP_ENV=production` 时，系统拒绝使用默认密码或开发用 `SECRET_KEY`。

模型文件：

- `models/fall_detection_yolo26s_best.pt`：YOLO 跌倒状态识别。
- `models/pose_landmarker_lite.task`：MediaPipe 多帧姿态和行为特征。

未配置 SMTP 时，站内告警仍可用，邮件任务重试三次后记录失败。

## 风险与事件

风险公式版本为 `v2`：个人及每日状态 20 分、行为 35 分、环境 25 分、时间因素 20 分。环境检查、每日问询、实时监测和视频分析都会生成新评估；历史评估不回写。

跌倒告警状态机：`pending -> confirmed/false_positive -> processing -> closed`。跌倒告警在倒计时内无人响应会自动升级并再次通知联系人。

## 验证命令

```text
python -m pytest -q
python -m ruff check .
cd web
pnpm run typecheck
pnpm run lint
pnpm run test
pnpm run build
```

PDF 报告包含风险趋势、四域评分、场景统计、行为事件、告警历史和干预记录；CSV 使用 UTF-8 BOM，便于 Excel 直接打开。
