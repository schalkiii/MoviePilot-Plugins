"""
躺平抽奖模块 - 独立调试脚本
运行方式：
  export TANGPT_COOKIE="你的cookie" && python3 test_debug.py
  或者直接运行（跳过HTTP测试）: python3 test_debug.py
"""

import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

# ============================================================
# 从插件中提取的静态方法（不依赖MoviePilot运行时）
# ============================================================

def extract_prize_name(item) -> Optional[str]:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ["name", "prize", "prize_name", "title", "reward",
                     "reward_name", "award", "award_name", "gift", "gift_name",
                     "content", "text", "description", "prize_type", "type"]:
            value = item.get(key)
            if value and isinstance(value, str):
                return value
    return None


def status_text(status) -> str:
    status_map = {
        "running": "进行中",
        "completed": "已完成",
        "error": "出错",
        "vip": "抽中VIP"
    }
    return status_map.get(status, str(status)) if status else "未知"


def safe_int(value, default: int = 0, min_value: int = 0) -> int:
    try:
        result = int(value)
        return max(result, min_value)
    except (ValueError, TypeError):
        return default


def calc_slot_ev(prize_rows: list, base_cost: int, jackpot_pool: int,
                 jackpot_hits: int = 0, total_spins_stat: int = 0) -> Tuple[float, str]:
    if not prize_rows or base_cost <= 0:
        return 0.0, "无数据"

    total_expected_payout = 0.0
    row_details = []
    for row in prize_rows:
        prob = row.get("probability", 0) / 100.0
        payout_mult = row.get("payout_multiplier", 0)
        payout = payout_mult * base_cost
        expected = prob * payout
        total_expected_payout += expected
        row_details.append(
            f"{row.get('name','?')}: "
            f"概率{row.get('probability',0):.2f}% × "
            f"派彩{payout:,} = "
            f"期望{expected:.2f}"
        )

    base_ev = total_expected_payout - base_cost
    base_rtp = total_expected_payout / base_cost * 100

    jackpot_ev = 0.0
    jackpot_prob = 0.0
    jackpot_detail = ""

    hits = jackpot_hits or 6
    spins = total_spins_stat or 19081
    jackpot_prob = hits / spins
    jackpot_ev = jackpot_prob * jackpot_pool
    triple_prob = 0
    for row in prize_rows:
        if row.get("rule_type") == "triple_any":
            triple_prob = row.get("probability", 0) / 100.0
            break
    if triple_prob > 0:
        p_symbol_given_triple = jackpot_prob / triple_prob * 100
        jackpot_detail = (
            f"Jackpot: {hits}/{spins}={jackpot_prob*100:.4f}% | "
            f"理论=P(三连={triple_prob*100:.2f}%)×P(7|三连={p_symbol_given_triple:.2f}%) | "
            f"奖池{jackpot_pool:,} × {jackpot_prob*100:.4f}% = 期望+{jackpot_ev:.2f}"
        )
    else:
        jackpot_detail = (
            f"Jackpot: {hits}/{spins}={jackpot_prob*100:.4f}% | "
            f"奖池{jackpot_pool:,} × {jackpot_prob*100:.4f}% = 期望+{jackpot_ev:.2f}"
        )

    total_ev = base_ev + jackpot_ev
    total_rtp = (total_expected_payout + jackpot_ev) / base_cost * 100

    detail_parts = [
        f"底注={base_cost:,}",
        f"--- 各等奖期望 ---",
    ] + row_details + [
        f"--- 汇总 ---",
        f"基础期望派彩={total_expected_payout:.2f}",
        f"基础EV={total_expected_payout:,} - {base_cost:,} = {base_ev:+,.2f}",
        f"基础RTP={base_rtp:.2f}%",
    ]
    if jackpot_detail:
        detail_parts.append(jackpot_detail)
    detail_parts.append(f"综合期望派彩={total_expected_payout+jackpot_ev:.2f}")
    detail_parts.append(f"综合EV={total_ev:+,.2f}/次")
    detail_parts.append(f"综合RTP={total_rtp:.2f}%")

    return total_ev, " | ".join(detail_parts)


def parse_page_state(html: str) -> Optional[dict]:
    """从HTML中提取__slotInitialState JSON（花括号计数法）"""
    state_start = html.find('__slotInitialState')
    if state_start < 0:
        return None
    brace_start = html.find('{', state_start)
    if brace_start < 0:
        return None
    depth = 0
    end_pos = brace_start
    for i in range(brace_start, len(html)):
        c = html[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                end_pos = i + 1
                break
    if depth != 0 or end_pos <= brace_start:
        return None
    try:
        return json.loads(html[brace_start:end_pos])
    except json.JSONDecodeError:
        return None


def parse_page_state_regex(html: str) -> Optional[dict]:
    """从HTML中提取page_state JSON（原正则方法，用于对比测试）"""
    config_match = re.search(r'__slotInitialState\s*=\s*({.+?});', html, re.DOTALL)
    if config_match:
        try:
            return json.loads(config_match.group(1))
        except json.JSONDecodeError:
            return None
    return None


# ============================================================
# 测试用例
# ============================================================

def test_extract_prize_name():
    print("\n===== 测试 extract_prize_name =====")
    cases = [
        ({"name": "魔力", "count": 80}, "魔力"),
        ({"prize": "100魔力"}, "100魔力"),
        ({"reward_name": "邀请码"}, "邀请码"),
        ({"title": "VIP"}, "VIP"),
        ({"name": "", "prize": "测试"}, "测试"),
        ({}, None),
        ("直接字符串", "直接字符串"),
        ({"unknown_key": "val"}, None),
    ]
    for item, expected in cases:
        result = extract_prize_name(item)
        status = "✅" if result == expected else "❌"
        print(f"  {status} extract_prize_name({item}) = {result!r} (期望={expected!r})")


def test_status_text():
    print("\n===== 测试 status_text =====")
    cases = [
        ("running", "进行中"),
        ("completed", "已完成"),
        ("error", "出错"),
        ("vip", "抽中VIP"),
        ("unknown", "unknown"),
        (None, "未知"),
        ("", "未知"),
    ]
    for status, expected in cases:
        result = status_text(status)
        status_icon = "✅" if result == expected else "❌"
        print(f"  {status_icon} status_text({status!r}) = {result!r} (期望={expected!r})")


def test_safe_int():
    print("\n===== 测试 safe_int =====")
    cases = [
        (100, 100, 0),
        (0, 0, 0),
        (-5, 0, 0),
        ("abc", 0, 0),
        (None, 0, 0),
        ("50", 50, 0),
        (3, 3, 1),
        (0, 1, 1),
    ]
    for value, expected, min_val in cases:
        result = safe_int(value, default=0, min_value=min_val)
        status_icon = "✅" if result == expected else "❌"
        print(f"  {status_icon} safe_int({value!r}, min={min_val}) = {result} (期望={expected})")


def test_calc_slot_ev():
    print("\n===== 测试 calc_slot_ev =====")

    # 模拟真实老虎机的prize_rows数据
    prize_rows = [
        {"name": "三连", "probability": 7.05, "payout_multiplier": 1.25, "rule_type": "triple_any"},
        {"name": "二连", "probability": 25.0, "payout_multiplier": 0.375, "rule_type": "double_any"},
    ]
    base_cost = 5000
    jackpot_pool = 500000

    ev, detail = calc_slot_ev(prize_rows, base_cost, jackpot_pool, 6, 19081)
    print(f"  EV = {ev:+.2f}")
    print(f"  明细: {detail[:200]}...")

    # 验证基础EV
    triple_ev = 0.0705 * (1.25 * 5000)
    double_ev = 0.25 * (0.375 * 5000)
    base_expected = triple_ev + double_ev
    base_ev = base_expected - 5000
    jackpot_ev = (6/19081) * 500000
    total_ev = base_ev + jackpot_ev

    print(f"  手动验算: 三连期望={triple_ev:.2f}, 二连期望={double_ev:.2f}")
    print(f"  基础期望派彩={base_expected:.2f}, 基础EV={base_ev:+.2f}")
    print(f"  Jackpot期望={jackpot_ev:.2f}, 综合EV={total_ev:+.2f}")

    assert abs(ev - total_ev) < 0.01, f"EV计算不匹配: {ev} != {total_ev}"
    print("  ✅ EV计算验证通过")

    # 测试空数据
    ev2, detail2 = calc_slot_ev([], 5000, 0)
    assert ev2 == 0.0 and detail2 == "无数据"
    print("  ✅ 空数据处理正确")

    # 测试jackpot_hits/total_spins_stat为0时使用兜底值
    ev3, detail3 = calc_slot_ev(prize_rows, base_cost, 1000000, 0, 0)
    print(f"  兜底值测试: EV={ev3:+.2f}")
    assert "6/19081" in detail3, f"兜底值未生效: {detail3[:100]}"
    print("  ✅ 兜底值测试通过")


def test_page_state_parsing():
    print("\n===== 测试 page_state 解析 =====")

    # 模拟包含嵌套JSON的HTML（使用真实网站的__slotInitialState格式）
    mock_html = """
    <html>
    <script>
    var __slotInitialState = {"config": {"base_cost": 5000, "daily_free_spins": 2, "prize_rows": [{"name": "三连", "probability": 7.05}]}, "global_stats": {"total_spins": 19081, "jackpot_hits": 6}};
    </script>
    </html>
    """

    # 新方法（花括号计数法）
    result_new = parse_page_state(mock_html)
    print(f"  新方法(花括号计数): {'✅ 成功' if result_new else '❌ 失败'}")
    if result_new:
        print(f"    解析结果: base_cost={result_new.get('config', {}).get('base_cost')}")
        print(f"    prize_rows={result_new.get('config', {}).get('prize_rows')}")
        assert result_new["config"]["base_cost"] == 5000
        assert len(result_new["config"]["prize_rows"]) == 1

    # 原方法（正则）
    result_old = parse_page_state_regex(mock_html)
    print(f"  原方法(正则): {'✅ 成功' if result_old else '❌ 失败'}")

    # 测试更复杂的嵌套（模拟真实网站5个prize_rows）
    complex_html = """
    <script>
    __slotInitialState = {"config": {"base_cost": 5000, "prize_rows": [{"name": "普通三连", "probability": 7.05, "payout_multiplier": 1.25}, {"name": "二连 AAB", "probability": 8.34, "payout_multiplier": 0.375}, {"name": "二连 ABA", "probability": 8.33, "payout_multiplier": 0.375}, {"name": "二连 BAA", "probability": 8.33, "payout_multiplier": 0.375}, {"name": "未中奖", "probability": 67.95, "payout_multiplier": 0}], "daily_free_spins": 2}, "global_stats": {"total_spins": 50000, "jackpot_hits": 12, "prize_summary": {"🍒": 1000, "🍋": 5000}}};
    </script>
    """
    result_complex = parse_page_state(complex_html)
    print(f"  复杂嵌套解析(5行): {'✅ 成功' if result_complex else '❌ 失败'}")
    if result_complex:
        prize_rows = result_complex.get("config", {}).get("prize_rows", [])
        print(f"    奖品行数: {len(prize_rows)}")
        assert len(prize_rows) == 5
        assert prize_rows[0]["name"] == "普通三连"
        assert result_complex["global_stats"]["total_spins"] == 50000

    # 测试无__slotInitialState的HTML
    no_state_html = "<html><body>Hello</body></html>"
    result_none = parse_page_state(no_state_html)
    assert result_none is None
    print(f"  无__slotInitialState: ✅ 正确返回None")


def test_lottery_response_parsing():
    print("\n===== 测试抽奖响应解析 =====")

    # 模拟真实API响应
    mock_response = {
        "ok": True,
        "items": [
            {"name": "魔力", "count": 80},
            {"name": "邀请码", "count": 1}
        ],
        "total_cost": 5000,
        "total_compensated": 0
    }

    if mock_response.get("ok"):
        prizes = []
        for item in mock_response.get("items", []):
            name = extract_prize_name(item)
            item_count = item.get("count", 1) if isinstance(item, dict) else 1
            if name:
                prizes.extend([name] * item_count)
        print(f"  解析奖品: {prizes}")
        assert len(prizes) == 81
        assert prizes.count("魔力") == 80
        assert prizes.count("邀请码") == 1
        print("  ✅ 抽奖响应解析正确")

    # 测试失败响应
    fail_response = {"ok": False, "msg": "Cookie无效"}
    if not fail_response.get("ok"):
        msg = fail_response.get("msg") or fail_response.get("message") or "抽奖失败"
        print(f"  失败响应: {msg}")
        assert msg == "Cookie无效"
        print("  ✅ 失败响应解析正确")


def test_slot_response_parsing():
    print("\n===== 测试老虎机响应解析 =====")

    # 模拟老虎机API响应
    mock_spin_response = {
        "ok": True,
        "result": "win",
        "reels": [
            {"name": "🍒", "symbol": "cherry"},
            {"name": "🍒", "symbol": "cherry"},
            {"name": "🍋", "symbol": "lemon"}
        ],
        "total_cost": 5000,
        "payout": 1875,
        "multiplier": 1,
        "is_free_spin": False,
        "is_jackpot": False,
        "jackpot_pool": 500000,
        "balance_after": 100000,
        "row": {"name": "二连", "payout_multiplier": 0.375},
        "spin_token": "abc123newtoken"
    }

    if isinstance(mock_spin_response, dict) and mock_spin_response.get("ok"):
        spin_result = mock_spin_response.get("result", "lose")
        is_jackpot = False
        row = mock_spin_response.get("row", {})
        if row:
            is_jackpot = row.get("is_jackpot", False)
        if not is_jackpot:
            is_jackpot = spin_result == "triple_win"
        new_spin_token = mock_spin_response.get("spin_token") or ""

        reels_info = " | ".join([r.get("name", "?") for r in mock_spin_response.get("reels", [])])
        print(f"  旋转结果: {spin_result}")
        print(f"  卷轴: [{reels_info}]")
        print(f"  派彩: {mock_spin_response.get('payout', 0)}")
        print(f"  新token: {new_spin_token[:20]}...")
        print(f"  Jackpot: {is_jackpot}")

        assert spin_result == "win"
        assert new_spin_token == "abc123newtoken"
        assert not is_jackpot
        print("  ✅ 老虎机响应解析正确")

    # 测试Jackpot响应
    jackpot_response = {
        "ok": True,
        "result": "triple_win",
        "reels": [
            {"name": "7️⃣", "symbol": "seven"},
            {"name": "7️⃣", "symbol": "seven"},
            {"name": "7️⃣", "symbol": "seven"}
        ],
        "total_cost": 5000,
        "payout": 500000,
        "multiplier": 1,
        "is_free_spin": False,
        "is_jackpot": True,
        "jackpot_pool": 500000,
        "balance_after": 1000000,
        "row": {"name": "Jackpot", "payout_multiplier": 100, "is_jackpot": True},
        "spin_token": "jackpotnewtoken"
    }

    if isinstance(jackpot_response, dict) and jackpot_response.get("ok"):
        spin_result = jackpot_response.get("result", "lose")
        is_jackpot = False
        row = jackpot_response.get("row", {})
        if row:
            is_jackpot = row.get("is_jackpot", False)
        if not is_jackpot:
            is_jackpot = spin_result == "triple_win"
        reels_info = " | ".join([r.get("name", "?") for r in jackpot_response.get("reels", [])])
        print(f"  Jackpot卷轴: [{reels_info}]")
        print(f"  Jackpot命中: {is_jackpot}")
        assert is_jackpot
        print("  ✅ Jackpot响应解析正确")


# ============================================================
# HTTP 测试（需要Cookie）
# ============================================================

COOKIE = os.environ.get("TANGPT_COOKIE", "")

DRAW_URL = "https://www.tangpt.top/web/omnibot/lottery/draw"
LOTTERY_PAGE_URL = "https://www.tangpt.top/omnibot_lottery.php"
SLOT_DRAW_URL = "https://www.tangpt.top/web/omnibot/slot-machine/draw"
SLOT_PAGE_URL = "https://www.tangpt.top/omnibot_slot.php"


def test_http_lottery_page():
    print("\n===== HTTP: 获取抽奖页面 =====")
    if not COOKIE:
        print("  ⏭️ 跳过（未设置TANGPT_COOKIE环境变量）")
        return
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "cookie": COOKIE,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        resp = requests.get(LOTTERY_PAGE_URL, headers=headers, timeout=15, verify=False)
        print(f"  状态码: {resp.status_code}")
        print(f"  页面长度: {len(resp.text)} 字符")
        if resp.status_code == 200:
            print("  ✅ 抽奖页面获取成功")
        else:
            print(f"  ❌ 抽奖页面获取失败: HTTP {resp.status_code}")
    except Exception as e:
        print(f"  ❌ 请求异常: {e}")


def test_http_lottery_draw():
    print("\n===== HTTP: 执行抽奖 =====")
    if not COOKIE:
        print("  ⏭️ 跳过（未设置TANGPT_COOKIE环境变量）")
        return
    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "x-requested-with": "XMLHttpRequest",
        "referer": LOTTERY_PAGE_URL,
        "cookie": COOKIE,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    data = {"count": "10"}
    try:
        resp = requests.post(DRAW_URL, headers=headers, data=data, timeout=30, verify=False)
        print(f"  状态码: {resp.status_code}")
        if resp.status_code == 200:
            result = resp.json()
            print(f"  响应: ok={result.get('ok')}, items={result.get('items', [])}")
            if result.get("ok"):
                prizes = []
                for item in result.get("items", []):
                    name = extract_prize_name(item)
                    item_count = item.get("count", 1) if isinstance(item, dict) else 1
                    if name:
                        prizes.extend([name] * item_count)
                print(f"  解析奖品: {dict(Counter(prizes))}")
                print("  ✅ 抽奖成功")
            else:
                print(f"  ❌ 抽奖失败: {result.get('msg', '未知')}")
        else:
            print(f"  ❌ HTTP {resp.status_code}")
    except Exception as e:
        print(f"  ❌ 异常: {e}")


def test_http_slot_page():
    print("\n===== HTTP: 获取老虎机页面 =====")
    if not COOKIE:
        print("  ⏭️ 跳过（未设置TANGPT_COOKIE环境变量）")
        return
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "cookie": COOKIE,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        resp = requests.get(SLOT_PAGE_URL, headers=headers, timeout=15, verify=False)
        print(f"  状态码: {resp.status_code}")
        print(f"  页面长度: {len(resp.text)} 字符")
        if resp.status_code != 200:
            print(f"  ❌ 老虎机页面获取失败: HTTP {resp.status_code}")
            return

        html = resp.text

        # 提取page_state（新方法）
        page_state = parse_page_state(html)
        if page_state:
            config = page_state.get("config", {})
            user_state = page_state.get("user_state", {}) or {}
            global_stats = config.get("global_stats", {}) or {}
            spin_token = (user_state.get("spin_token", "") or None) or None
            print(f"  page_state解析: ✅ 成功")
            print(f"  spin_token(来自JSON): {'✅ ' + spin_token[:16] + '...' if spin_token else '❌ 未找到'}")
            print(f"    base_cost={config.get('base_cost')}")
            print(f"    daily_free_spins={config.get('daily_free_spins')}")
            print(f"    daily_play_limit={config.get('daily_play_limit')}")
            print(f"    prize_rows数量={len(config.get('prize_rows', []))}")
            for pr in config.get("prize_rows", []):
                print(f"      - {pr.get('name')}: 概率{pr.get('probability')}%, 倍率{pr.get('payout_multiplier')}")
            print(f"    jackpot_pool={config.get('jackpot_pool')}")
            print(f"    global_stats: {json.dumps(global_stats, ensure_ascii=False)}")

            # 计算EV
            base_cost = config.get("base_cost", 5000)
            jackpot_pool = config.get("jackpot_pool", 0) or 0
            prize_rows = config.get("prize_rows", [])
            jackpot_hits = global_stats.get("jackpot_hits", 0) or 0
            total_spins = global_stats.get("total_spins", 0) or 0
            ev, ev_detail = calc_slot_ev(prize_rows, base_cost, jackpot_pool, jackpot_hits, total_spins)
            print(f"  EV计算: {ev:+.2f}/次")
            print(f"  明细: {ev_detail}")
        else:
            print(f"  page_state解析: ❌ 失败")

    except Exception as e:
        print(f"  ❌ 异常: {e}")


def test_http_slot_spin():
    print("\n===== HTTP: 老虎机旋转 =====")
    if not COOKIE:
        print("  ⏭️ 跳过（未设置TANGPT_COOKIE环境变量）")
        return

    # 先获取页面获取spin_token
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "cookie": COOKIE,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        resp = requests.get(SLOT_PAGE_URL, headers=headers, timeout=15, verify=False)
        if resp.status_code != 200:
            print(f"  ❌ 获取页面失败: HTTP {resp.status_code}")
            return
        html = resp.text
        token_match = re.search(r'spin_token["\s:=]+["\']?([a-f0-9]{32})["\']?', html)
        spin_token = token_match.group(1) if token_match else None
        if not spin_token:
            print("  ❌ 未获取到spin_token")
            return
        print(f"  获取到spin_token: {spin_token[:16]}...")

        # 执行免费旋转
        spin_headers = {
            "accept": "application/json, text/javascript, */*; q=0.01",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "x-requested-with": "XMLHttpRequest",
            "referer": SLOT_PAGE_URL,
            "cookie": COOKIE,
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        spin_data = {"multiplier": "1", "spin_token": spin_token}
        spin_resp = requests.post(SLOT_DRAW_URL, headers=spin_headers, data=spin_data, timeout=30, verify=False)
        print(f"  旋转状态码: {spin_resp.status_code}")
        if spin_resp.status_code == 200:
            result = spin_resp.json()
            print(f"  响应: ok={result.get('ok')}, result={result.get('result')}")
            if result.get("ok"):
                reels_info = " | ".join([r.get("name", "?") for r in result.get("reels", [])])
                print(f"  卷轴: [{reels_info}]")
                print(f"  派彩: {result.get('payout', 0)}")
                print(f"  花费: {result.get('total_cost', 0)}")
                new_token = result.get("spin_token", "")
                print(f"  新spin_token: {'✅ 已更新' if new_token else '❌ 未返回新token'}")
                print("  ✅ 老虎机旋转成功")
            else:
                print(f"  ❌ 旋转失败: {result.get('msg', '未知')}")
        else:
            print(f"  ❌ HTTP {spin_resp.status_code}")

    except Exception as e:
        print(f"  ❌ 异常: {e}")


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    print("=" * 60)
    print("  躺平抽奖模块 - 独立调试脚本")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Cookie状态: {'✅ 已设置' if COOKIE else '⏭️ 未设置（跳过HTTP测试）'}")
    print("=" * 60)

    # 单元测试
    test_extract_prize_name()
    test_status_text()
    test_safe_int()
    test_calc_slot_ev()
    test_page_state_parsing()
    test_lottery_response_parsing()
    test_slot_response_parsing()

    # HTTP测试（需要Cookie）
    test_http_lottery_page()
    test_http_lottery_draw()
    test_http_slot_page()
    test_http_slot_spin()

    print("\n" + "=" * 60)
    print("  所有测试完成")
    print("=" * 60)