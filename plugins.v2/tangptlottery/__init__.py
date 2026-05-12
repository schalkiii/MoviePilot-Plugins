import re
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from html import unescape
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3
from apscheduler.triggers.cron import CronTrigger
from urllib3.exceptions import InsecureRequestWarning

from app.core.event import Event, eventmanager
from app.db.site_oper import SiteOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.schemas.types import EventType

urllib3.disable_warnings(InsecureRequestWarning)


class TangptLottery(_PluginBase):
    plugin_name = "躺平自动抽奖助手"
    plugin_desc = "躺平站点自动抽奖，支持定时抽奖、中奖通知、获取站点Cookie等功能。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.0.0"
    plugin_author = ""
    author_url = ""
    plugin_config_prefix = "tangptlottery_"
    plugin_order = 30
    auth_level = 2

    DRAW_URL = "https://www.tangpt.top/web/omnibot/lottery/draw"
    LOTTERY_PAGE_URL = "https://www.tangpt.top/omnibot_lottery.php"
    SITE_DOMAIN = "tangpt.top"
    MAX_HISTORY = 30

    _enabled = False
    _cookie = ""
    _draw_count = 100
    _target_count = 1000
    _cron = "10 2 * * *"
    _notify = True
    _run_once = False
    _lock = threading.Lock()

    def init_plugin(self, config: dict = None):
        config = config or {}
        site_cookie = self.__get_site_cookie()
        self._enabled = bool(config.get("enabled", False))
        self._cookie = (config.get("cookie") or site_cookie or "").strip()
        self._draw_count = self.__safe_int(config.get("draw_count"), 100, min_value=1)
        self._target_count = self.__safe_int(config.get("target_count"), 1000, min_value=1)
        self._cron = (config.get("cron") or "10 2 * * *").strip()
        self._notify = bool(config.get("notify", True))
        self._run_once = bool(config.get("run_once", False))
        logger.info(
            f"躺平自动抽奖助手初始化完成：enabled={self._enabled}, "
            f"draw_count={self._draw_count}, target_count={self._target_count}, "
            f"cron={self._cron}, notify={self._notify}"
        )
        if self._run_once:
            self._run_once = False
            self.update_config({
                "enabled": self._enabled,
                "cookie": self._cookie,
                "draw_count": self._draw_count,
                "target_count": self._target_count,
                "cron": self._cron,
                "notify": self._notify,
                "run_once": False
            })
            logger.info("收到配置页立即运行请求，后台启动抽奖任务")
            threading.Thread(target=self.run_lottery_task, daemon=True).start()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/tpcj",
                "event": EventType.PluginAction,
                "desc": "执行躺平抽奖，可指定次数 /tpcj 10",
                "category": "抽奖",
                "data": {"action": "tangpt_lottery"}
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/run",
                "endpoint": self.run_once_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即执行躺平抽奖",
                "description": "按当前插件配置立即执行一次躺平抽奖任务。"
            },
            {
                "path": "/get_cookie",
                "endpoint": self.get_cookie_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取躺平站点Cookie",
                "description": "从站点管理中获取躺平站点的Cookie。"
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled or not self._cron:
            return []
        try:
            trigger = CronTrigger.from_crontab(self._cron)
        except ValueError:
            logger.warn("躺平自动抽奖助手 Cron 配置无效，定时服务未注册")
            return []
        return [
            {
                "id": "TangptLottery",
                "name": "躺平自动抽奖",
                "trigger": trigger,
                "func": self.run_lottery_task,
                "kwargs": {}
            }
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        site_cookie = self.__get_site_cookie()
        cookie_value = self._cookie or site_cookie or ""
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "enabled", "label": "启用插件"}
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "notify", "label": "发送通知"}
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "run_once",
                                            "label": "立即运行一次",
                                            "hint": "保存配置后执行，并自动关闭"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VBtn",
                                        "props": {
                                            "color": "primary",
                                            "variant": "tonal",
                                            "text": "立即执行一次"
                                        },
                                        "events": {
                                            "click": {
                                                "api": "plugin/TangptLottery/run",
                                                "method": "post"
                                            }
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "draw_count",
                                            "label": "每次抽奖数量",
                                            "type": "number",
                                            "min": 1,
                                            "hint": "单次请求抽奖次数"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "target_count",
                                            "label": "每日目标总次数",
                                            "type": "number",
                                            "min": 1,
                                            "hint": "每天总共抽奖次数"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VCronField",
                                        "props": {
                                            "model": "cron",
                                            "label": "执行周期",
                                            "placeholder": "5位 Cron 表达式，例如 10 2 * * *"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 10},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "cookie",
                                            "label": "躺平站点 Cookie",
                                            "rows": 3,
                                            "placeholder": "填写包含 c_secure_pass 的完整 Cookie",
                                            "hint": "留空时读取站点管理中的躺平站点 Cookie；填写后仅本插件使用，不会修改站点 Cookie"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 2,
                                    "class": "d-flex align-center"
                                },
                                "content": [
                                    {
                                        "component": "VBtn",
                                        "props": {
                                            "color": "success",
                                            "variant": "tonal",
                                            "text": "获取Cookie"
                                        },
                                        "events": {
                                            "click": {
                                                "api": "plugin/TangptLottery/get_cookie",
                                                "method": "get"
                                            }
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": self._enabled,
            "cookie": cookie_value,
            "draw_count": self._draw_count,
            "target_count": self._target_count,
            "cron": self._cron,
            "notify": self._notify,
            "run_once": False
        }

    def get_page(self) -> List[dict]:
        records = self.__get_records()
        for record in records:
            record["status_text"] = record.get("status_text") or self.__status_text(record.get("status"))
        lottery_info = self.__fetch_lottery_info()
        today_summary, yesterday_summary = self.__build_recent_prize_summary(records)
        return [
            {
                "component": "VCard",
                "props": {"variant": "tonal", "class": "mb-4"},
                "content": [
                    {
                        "component": "VCardTitle",
                        "text": "我的抽奖信息"
                    },
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "VRow",
                                "content": [
                                    self.__info_col("每次抽奖数", lottery_info.get("draw_count")),
                                    self.__info_col("今日已抽", lottery_info.get("today_drawn")),
                                    self.__info_col("今日目标", lottery_info.get("target_count")),
                                    self.__info_col("状态", lottery_info.get("status")),
                                ]
                            },
                            {
                                "component": "div",
                                "props": {"class": "text-caption text-medium-emphasis mt-2"},
                                "text": lottery_info.get("message") or f"更新时间：{lottery_info.get('updated_at')}"
                            }
                        ]
                    }
                ]
            },
            {
                "component": "VDataTable",
                "props": {
                    "headers": [
                        {"title": "日期", "key": "date"},
                        {"title": "目标", "key": "target_count"},
                        {"title": "完成", "key": "completed_count"},
                        {"title": "请求次数", "key": "request_count"},
                        {"title": "奖品汇总", "key": "prize_text"},
                        {"title": "状态", "key": "status_text"},
                        {"title": "消息", "key": "message"}
                    ],
                    "items": records,
                    "items-per-page": 10,
                    "hide-default-footer": True,
                    "density": "compact"
                }
            },
            {
                "component": "VDivider",
                "props": {"class": "my-4"}
            },
            {
                "component": "div",
                "props": {"class": "text-h6 mb-3"},
                "text": "奖品名称汇总"
            },
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 6},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {"variant": "tonal", "class": "h-100"},
                                "content": [
                                    {
                                        "component": "VCardTitle",
                                        "text": "今日汇总"
                                    },
                                    {
                                        "component": "VCardText",
                                        "content": [
                                            {
                                                "component": "VRow",
                                                "props": {"dense": True},
                                                "content": self.__summary_grid(today_summary)
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 6},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {"variant": "tonal", "class": "h-100"},
                                "content": [
                                    {
                                        "component": "VCardTitle",
                                        "text": "昨日汇总"
                                    },
                                    {
                                        "component": "VCardText",
                                        "content": [
                                            {
                                                "component": "VRow",
                                                "props": {"dense": True},
                                                "content": self.__summary_grid(yesterday_summary)
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    def run_once_api(self):
        threading.Thread(target=self.run_lottery_task, daemon=True).start()
        return {"status": "started", "message": "躺平抽奖任务已启动"}

    def get_cookie_api(self):
        result = self.__get_site_cookie_detail()
        if result.get("success"):
            cookie = result.get("cookie", "")
            self._cookie = cookie
            self.update_config({
                "enabled": self._enabled,
                "cookie": cookie,
                "draw_count": self._draw_count,
                "target_count": self._target_count,
                "cron": self._cron,
                "notify": self._notify,
                "run_once": False
            })
            return {"success": True, "cookie": cookie, "message": "Cookie获取成功"}
        return {"success": False, "cookie": "", "message": result.get("msg", "获取Cookie失败")}

    def run_lottery_task(self, override_count: int = None):
        with self._lock:
            try:
                logger.info("躺平自动抽奖任务开始执行")
                if not self._cookie:
                    logger.error("躺平自动抽奖：未配置Cookie，无法执行抽奖")
                    if self._notify:
                        self.post_message(
                            mtype=NotificationType.SiteMessage,
                            title="【躺平自动抽奖助手】",
                            text="未配置Cookie，无法执行抽奖任务"
                        )
                    return

                today = datetime.now().strftime("%Y-%m-%d")
                records = self.__get_records()
                today_record = None
                for r in records:
                    if r.get("date") == today:
                        today_record = r
                        break

                if not today_record:
                    today_record = {
                        "date": today,
                        "target_count": override_count or self._target_count,
                        "completed_count": 0,
                        "request_count": 0,
                        "prizes": [],
                        "status": "running",
                        "message": ""
                    }
                    records.insert(0, today_record)

                target = override_count or self._target_count
                today_record["target_count"] = target
                completed = today_record.get("completed_count", 0)

                if completed >= target:
                    logger.info(f"躺平自动抽奖：今日已完成 {completed}/{target}，达到目标")
                    today_record["status"] = "completed"
                    today_record["message"] = "已达目标次数"
                    self.__save_records(records)
                    return

                all_prizes = today_record.get("prizes", [])
                request_count = today_record.get("request_count", 0)

                while completed < target:
                    draw_count = min(self._draw_count, target - completed)
                    result = self.__do_draw(draw_count)

                    if not result.get("success"):
                        today_record["status"] = "error"
                        today_record["message"] = result.get("message", "抽奖请求失败")
                        today_record["completed_count"] = completed
                        today_record["request_count"] = request_count
                        today_record["prizes"] = all_prizes
                        self.__save_records(records)
                        if self._notify:
                            self.post_message(
                                mtype=NotificationType.SiteMessage,
                                title="【躺平自动抽奖助手】",
                                text=f"抽奖出错：{result.get('message', '未知错误')}\n已完成：{completed}/{target}"
                            )
                        return

                    prizes = result.get("prizes", [])
                    all_prizes.extend(prizes)
                    completed += draw_count
                    request_count += 1

                    today_record["completed_count"] = completed
                    today_record["request_count"] = request_count
                    today_record["prizes"] = all_prizes
                    today_record["message"] = f"已完成 {completed}/{target}"

                    vip_prize = any("VIP" in p or "vip" in p for p in prizes)
                    if vip_prize:
                        logger.info("躺平自动抽奖：抽中VIP，停止抽奖")
                        today_record["status"] = "vip"
                        today_record["message"] = f"抽中VIP！已完成 {completed}/{target}"
                        self.__save_records(records)
                        if self._notify:
                            self.__send_lottery_notification(today_record, all_prizes)
                        return

                    time.sleep(1)

                today_record["status"] = "completed"
                today_record["message"] = f"完成 {completed}/{target}"
                self.__save_records(records)

                if self._notify:
                    self.__send_lottery_notification(today_record, all_prizes)

                logger.info(f"躺平自动抽奖任务完成，共抽奖 {completed} 次")

            except Exception as e:
                logger.error(f"躺平自动抽奖任务异常：{e}")
                if self._notify:
                    self.post_message(
                        mtype=NotificationType.SiteMessage,
                        title="【躺平自动抽奖助手】",
                        text=f"抽奖任务异常：{str(e)}"
                    )

    @eventmanager.register(EventType.PluginAction)
    def handle_command(self, event: Event):
        if event.event_data.get("action") != "tangpt_lottery":
            return
        override_count = event.event_data.get("args")
        if override_count:
            try:
                override_count = int(override_count)
            except (ValueError, TypeError):
                override_count = None
        threading.Thread(
            target=self.run_lottery_task,
            args=(override_count,),
            daemon=True
        ).start()

    def __do_draw(self, count: int) -> Dict[str, Any]:
        try:
            headers = {
                "accept": "application/json, text/javascript, */*; q=0.01",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "x-requested-with": "XMLHttpRequest",
                "referer": self.LOTTERY_PAGE_URL,
                "cookie": self._cookie,
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
            }
            data = {"count": str(count)}
            response = requests.post(
                self.DRAW_URL,
                headers=headers,
                data=data,
                timeout=30,
                verify=False
            )
            if response.status_code != 200:
                return {"success": False, "message": f"HTTP {response.status_code}"}

            try:
                result = response.json()
            except Exception:
                return {"success": False, "message": f"响应解析失败: {response.text[:200]}"}

            prizes = []
            if isinstance(result, dict):
                if result.get("status") == "error" or result.get("ret") == "error":
                    return {"success": False, "message": result.get("msg") or result.get("message") or "抽奖失败"}

                data_field = result.get("data") or result.get("result") or result
                if isinstance(data_field, list):
                    for item in data_field:
                        if isinstance(item, dict):
                            prize_name = item.get("prize") or item.get("name") or item.get("title") or item.get("reward") or str(item)
                            prizes.append(prize_name)
                        elif isinstance(item, str):
                            prizes.append(item)
                elif isinstance(data_field, dict):
                    items = data_field.get("items") or data_field.get("prizes") or data_field.get("list") or []
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict):
                                prize_name = item.get("prize") or item.get("name") or item.get("title") or item.get("reward") or str(item)
                                prizes.append(prize_name)
                            elif isinstance(item, str):
                                prizes.append(item)
                    else:
                        msg = data_field.get("msg") or data_field.get("message") or ""
                        if msg:
                            prizes.append(msg)

                if not prizes:
                    msg = result.get("msg") or result.get("message") or ""
                    if msg:
                        prizes.append(msg)

            return {"success": True, "prizes": prizes, "raw": result}

        except requests.exceptions.RequestException as e:
            return {"success": False, "message": f"请求异常: {str(e)}"}
        except Exception as e:
            return {"success": False, "message": f"未知异常: {str(e)}"}

    def __fetch_lottery_info(self) -> Dict[str, Any]:
        info = {
            "draw_count": self._draw_count,
            "today_drawn": 0,
            "target_count": self._target_count,
            "status": "未知",
            "message": "",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            records = self.__get_records()
            for r in records:
                if r.get("date") == today:
                    info["today_drawn"] = r.get("completed_count", 0)
                    info["status"] = self.__status_text(r.get("status"))
                    info["message"] = r.get("message", "")
                    break
        except Exception as e:
            logger.error(f"获取抽奖信息失败: {e}")
        return info

    def __get_site_cookie(self) -> str:
        try:
            siteoper = SiteOper()
            site = siteoper.get_by_domain(self.SITE_DOMAIN)
            if site and site.cookie:
                return site.cookie
        except Exception:
            pass
        return ""

    def __get_site_cookie_detail(self) -> Dict[str, Any]:
        try:
            siteoper = SiteOper()
            site = siteoper.get_by_domain(self.SITE_DOMAIN)
            if not site:
                return {"success": False, "msg": f"未添加躺平站点({self.SITE_DOMAIN})！请在站点管理中添加。"}
            cookie = site.cookie
            if not cookie or str(cookie).strip().lower() == "cookie":
                return {"success": False, "msg": "站点Cookie为空或无效，请在站点管理中配置！"}
            return {"success": True, "cookie": cookie}
        except Exception as e:
            logger.error(f"获取站点Cookie失败: {e}")
            return {"success": False, "msg": f"获取站点Cookie失败: {e}"}

    def __send_lottery_notification(self, record: dict, prizes: list):
        prize_counter = Counter(prizes)
        prize_text = "\n".join([f"  {name}: {count}次" for name, count in prize_counter.most_common()])
        if not prize_text:
            prize_text = "  无奖品记录"
        self.post_message(
            mtype=NotificationType.SiteMessage,
            title="【躺平自动抽奖助手】",
            text=f"日期：{record.get('date')}\n"
                 f"完成：{record.get('completed_count', 0)}/{record.get('target_count', 0)}\n"
                 f"状态：{self.__status_text(record.get('status'))}\n"
                 f"奖品：\n{prize_text}"
        )

    def __get_records(self) -> List[dict]:
        try:
            records = self.get_data("lottery_records") or []
        except Exception:
            records = []
        return records[:self.MAX_HISTORY]

    def __save_records(self, records: List[dict]):
        for record in records:
            prizes = record.get("prizes", [])
            counter = Counter(prizes)
            parts = []
            for name, count in counter.most_common():
                if count > 1:
                    parts.append(f"{name}x{count}")
                else:
                    parts.append(name)
            record["prize_text"] = "、".join(parts) if parts else "无"
        self.save_data("lottery_records", records[:self.MAX_HISTORY])

    def __build_recent_prize_summary(self, records: List[dict]):
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        today_summary = Counter()
        yesterday_summary = Counter()
        for r in records:
            if r.get("date") == today:
                today_summary.update(r.get("prizes", []))
            elif r.get("date") == yesterday:
                yesterday_summary.update(r.get("prizes", []))
        return today_summary, yesterday_summary

    @staticmethod
    def __summary_grid(summary: Counter) -> List[dict]:
        if not summary:
            return [
                {
                    "component": "VCol",
                    "props": {"cols": 12},
                    "content": [
                        {
                            "component": "div",
                            "props": {"class": "text-body-2 text-medium-emphasis"},
                            "text": "暂无数据"
                        }
                    ]
                }
            ]
        items = []
        for name, count in summary.most_common():
            items.append(
                {
                    "component": "VCol",
                    "props": {"cols": 6, "md": 4},
                    "content": [
                        {
                            "component": "VChip",
                            "props": {
                                "label": True,
                                "size": "small",
                                "variant": "tonal",
                                "class": "ma-1"
                            },
                            "content": [
                                {
                                    "component": "span",
                                    "text": f"{name} ×{count}"
                                }
                            ]
                        }
                    ]
                }
            )
        return items

    @staticmethod
    def __info_col(label: str, value) -> dict:
        return {
            "component": "VCol",
            "props": {"cols": 6, "md": 3},
            "content": [
                {
                    "component": "div",
                    "props": {"class": "text-caption text-medium-emphasis"},
                    "text": str(label)
                },
                {
                    "component": "div",
                    "props": {"class": "text-h6"},
                    "text": str(value if value is not None else "-")
                }
            ]
        }

    @staticmethod
    def __status_text(status) -> str:
        status_map = {
            "running": "进行中",
            "completed": "已完成",
            "error": "出错",
            "vip": "抽中VIP"
        }
        return status_map.get(status, str(status)) if status else "未知"

    @staticmethod
    def __safe_int(value, default: int = 0, min_value: int = 0) -> int:
        try:
            result = int(value)
            return max(result, min_value)
        except (ValueError, TypeError):
            return default

    def stop_service(self):
        pass
