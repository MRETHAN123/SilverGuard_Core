"""SilverGuard 命令行入口：直接运行 python main.py，不需要网页或 npm。"""

import config
from silverguard.core import analyze, summarize
from silverguard.agent import apply_agent


def show_result(result):
    auto_label = {
        True: "输入文字提示已开启自动续费",
        False: "输入文字提示已关闭自动续费",
        None: "尚不能判断自动续费状态",
    }
    amount = result["amount"]
    amount_text = f"{amount:g} 元" if amount is not None else "待确认"

    print("\n===== 账单分析结果 =====")
    print(f"服务名称：{result['service']}")
    if result.get("service_source"):
        print(f"服务识别来源：{result['service_source']}（置信度：{result.get('service_confidence', '未知')}）")
    print(f"服务类别：{result['category']}")
    if result.get("category_source"):
        print(f"类别来源：{result['category_source']}")
    print(f"服务说明：{result['what']}")
    print(f"消费金额：{amount_text}")
    print(f"续费状态：{auto_label[result['auto_renew']]}")
    print(f"风险级别：{result['risk_level']}")
    print(f"扣费解释：{result['why']}")
    if result["analogy"]:
        print(f"生活类比：{result['analogy']}")
    if result["risks"]:
        print("风险提醒：")
        for risk in result["risks"]:
            print(f"  - {risk['message']}")
    print("下一步建议：")
    for number, advice in enumerate(result["next_steps"], start=1):
        print(f"  {number}. {advice}")
    print(f"运行模式：{result['mode']}")
    if config.ENABLE_AGENT:
        print(f"模型调用：{result['llm_status']}")
    if result.get("llm_risks") or result.get("llm_next_steps"):
        print("大模型补充分析（根据输入文字推断，尚未核实）：")
        for note in result.get("llm_risks", []):
            print(f"  - 风险提示：{note}")
        for step in result.get("llm_next_steps", []):
            print(f"  - 建议：{step}")
        if result.get("llm_source_note"):
            print(f"  {result['llm_source_note']}")
    print(f"说明：{result['notice']}\n")


def show_summary(results):
    if not results:
        print("还没有输入过账单。")
        return
    summary = summarize(results)
    print("\n===== 本次输入的账单汇总 =====")
    for category, item in summary["categories"].items():
        print(
            f"{category}：{item['count']} 笔，已知金额合计 "
            f"{item['known_amount_total']:g} 元，金额未知 {item['unknown_amount_count']} 笔"
        )
    print(summary["scope"] + "\n")


def main():
    print("SilverGuard 纯 Python 核心版")
    print("配置位置：config.py；Agent 状态：" + ("已启用" if config.ENABLE_AGENT else "未启用（仅规则分析）"))
    print("直接输入一笔账单；输入 summary 查看本次汇总，输入 q 退出。")
    results = []

    while True:
        try:
            bill = input("\n账单> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            break
        if bill.lower() in {"q", "quit", "exit"}:
            print("已退出。")
            break
        if bill.lower() == "summary":
            show_summary(results)
            continue
        if not bill:
            continue
        try:
            result = apply_agent(analyze(bill), original_text=bill)
        except ValueError as exc:
            print(f"输入错误：{exc}")
            continue
        results.append(result)
        show_result(result)


if __name__ == "__main__":
    main()
