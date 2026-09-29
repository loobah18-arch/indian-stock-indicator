#!/usr/bin/env python3
import urllib.request
import json
import sys

BASE_URL = "http://localhost:5000"

def test_endpoint(name, path, method="GET", payload=None):
    url = BASE_URL + path
    headers = {"Content-Type": "application/json"}
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            print(f"✓ [{method}] {path} -> OK (Status {resp.status})")
            return data
    except Exception as e:
        print(f"✗ [{method}] {path} -> FAILED: {e}")
        sys.exit(1)

def main():
    print("==================================================")
    print("Testing Virtual $1,000 AI Portfolio & P&L Engine")
    print("==================================================")

    # 1. Reset portfolio to clean $1,000
    res = test_endpoint("Reset", "/api/portfolio/reset", method="POST")
    assert res.get("starting_balance") == 1000.0, f"Expected 1000.0, got {res.get('starting_balance')}"
    assert res.get("cash") == 1000.0, f"Expected 1000.0 cash, got {res.get('cash')}"
    assert len(res.get("positions", [])) == 0, "Expected empty positions"
    print("  -> Initial State: $1,000.00 Cash, 0 Positions")

    # 2. Test Auto-Invest in Top AI Picks
    invest_res = test_endpoint("Auto-Invest", "/api/portfolio/auto-invest", method="POST", payload={"market": "US"})
    executed = invest_res.get("executed", [])
    summary = invest_res.get("summary", {})
    print(f"  -> Auto-invested in {len(executed)} top AI picks: {[e['symbol'] for e in executed]}")
    print(f"  -> Total Equity: ${summary.get('total_equity'):.2f}, Cash: ${summary.get('cash'):.2f}")
    assert len(executed) > 0, "Expected at least 1 executed trade"
    assert summary.get("total_equity") > 0, "Expected positive equity"

    # 3. Test Selling 1 position to lock profit and record win/loss
    first_sym = executed[0]["symbol"]
    entry_p = executed[0]["price"]
    exit_p = round(entry_p * 1.04, 2) # simulate +4% win
    sell_res = test_endpoint("Sell Position", "/api/portfolio/sell", method="POST", payload={
        "symbol": first_sym,
        "price": exit_p,
        "reason": "TAKE_PROFIT_1"
    })
    assert sell_res.get("success") is True, "Expected successful sell"
    assert sell_res.get("result") == "WIN", "Expected WIN outcome"
    print(f"  -> Sold {first_sym} at ${exit_p} for P&L: +${sell_res.get('pnl')} ({sell_res.get('pnl_pct')}%)")

    # 4. Verify Portfolio Metrics
    port = test_endpoint("Get Summary", "/api/portfolio")
    assert port.get("total_trades") == 1, "Expected 1 closed trade"
    assert port.get("wins") == 1, "Expected 1 win"
    assert port.get("win_rate_pct") == 100.0, "Expected 100% win rate"
    assert port.get("realized_pnl") > 0, "Expected positive realized P&L"
    print(f"  -> Performance: Total Equity ${port.get('total_equity'):.2f} | Net Return: +{port.get('total_pnl_pct')}% | Win Rate: {port.get('win_rate_pct')}%")

    # 5. Generate AI Quantitative P&L & Probability Audit Report
    print("  -> Requesting AI Quantitative Audit Report...")
    report_res = test_endpoint("AI Audit Report", "/api/portfolio/report")
    assert report_res.get("error") is False, "Expected error=False"
    assert len(report_res.get("report", "")) > 50, "Expected substantive report text"
    print(f"  -> AI Model Used: {report_res.get('model')}")
    print(f"  -> Report Preview:\n{report_res.get('report')[:200]}...")

    print("==================================================")
    print("ALL 5/5 INTEGRATION TESTS PASSED!")
    print("==================================================")

if __name__ == "__main__":
    main()
