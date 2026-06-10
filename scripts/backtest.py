"""回测历届世界杯。用法： python scripts/backtest.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wc2026.backtest.runner import backtest_ensemble


def main() -> None:
    print(f"{'届':>6} {'场次':>5} {'跳过':>5} {'LogLoss':>9} {'基准':>8} {'Brier':>8} {'准确率':>8}")
    print("-" * 60)
    for y in ["2010", "2014", "2018", "2022"]:
        r = backtest_ensemble(y)
        print(f"{y:>6} {r['n']:>5} {r['skipped']:>5} {r['log_loss']:>9.4f} "
              f"{r['baseline_log_loss']:>8.4f} {r['brier']:>8.4f} {r['accuracy']:>7.1%}")
    print("-" * 60)
    print("LogLoss < 基准1.0986 = 比瞎猜有预测力；准确率参考(三分类随机≈33%，世界杯爆冷多)。")
    print("\n2022 校准曲线(pred≈actual 为佳):")
    for c in backtest_ensemble("2022")["calibration"]:
        print(f"  概率{c['range']}: 预测均值{c['pred_mean']:.3f} 实际频率{c['actual_freq']:.3f} (n={c['n']})")


if __name__ == "__main__":
    main()
