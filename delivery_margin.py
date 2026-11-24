#!/usr/bin/env python3
"""
Delivery margin on fixed-price integration work.

The problem this answers: when integrations are sold at a fixed price and
delivered as projects, revenue is known on day one and margin is not. Margin is
decided later, quietly, by how many hours the work actually took. By the time it
shows up in a P&L the engagement is closed and nobody can say which decision
cost the money.

This splits delivered margin into the three things that move it:
  scope     hours beyond what was quoted, on work that was in scope
  creep     hours on work that was never quoted at all
  rework    hours spent doing the same deliverable twice

They look identical in a timesheet total and have different fixes. Scope is an
estimating problem, creep is a contracting problem, rework is a quality problem.

Run:
    python3 delivery_margin.py            # writes report.md + engagements.csv
    python3 delivery_margin.py --test     # self-check

Every figure is synthetic, generated here from a fixed seed. It is a worked
method on invented numbers, not a claim about anyone's real engagements.
"""
import argparse, csv, random, sys
from collections import defaultdict

TARGET_MARGIN = 0.55          # what a fixed-price engagement is sold to earn
MATERIALITY_USD = 15_000      # below this, a miss is not worth a sentence
TOP_N = 5


def sample_rows(seed=11):
    rnd = random.Random(seed)
    segments = ["Mid-market SaaS", "Enterprise SaaS", "Platform ISV"]
    systems = ["ERP", "CRM", "Billing", "Data warehouse", "Ticketing"]
    rows = []
    for i in range(1, 29):
        seg = segments[i % 3]
        system = systems[i % 5]
        quarter = "2026-Q3" if i <= 14 else "2026-Q4"
        price = rnd.randrange(40_000, 220_000)
        blended_rate = rnd.choice([55, 65, 75])
        quoted_hours = int(price * (1 - TARGET_MARGIN) / blended_rate)
        # the three ways hours appear that nobody quoted
        scope = int(quoted_hours * rnd.uniform(0.0, 0.35))
        creep = int(quoted_hours * rnd.uniform(0.0, 0.30))
        rework = int(quoted_hours * rnd.uniform(0.0, 0.22))
        rows.append({
            "engagement": f"ENG-{i:03d}", "segment": seg, "system": system,
            "quarter": quarter, "price_usd": price, "rate_usd": blended_rate,
            "quoted_hours": quoted_hours, "scope_hours": scope,
            "creep_hours": creep, "rework_hours": rework,
        })
    return rows


def enrich(rows):
    for r in rows:
        extra = r["scope_hours"] + r["creep_hours"] + r["rework_hours"]
        r["delivered_hours"] = r["quoted_hours"] + extra
        r["quoted_cost_usd"] = r["quoted_hours"] * r["rate_usd"]
        r["delivered_cost_usd"] = r["delivered_hours"] * r["rate_usd"]
        r["target_margin_usd"] = r["price_usd"] - r["quoted_cost_usd"]
        r["actual_margin_usd"] = r["price_usd"] - r["delivered_cost_usd"]
        r["margin_miss_usd"] = r["target_margin_usd"] - r["actual_margin_usd"]
        r["actual_margin_pct"] = (r["actual_margin_usd"] / r["price_usd"]
                                  if r["price_usd"] else 0.0)
        for k in ("scope", "creep", "rework"):
            r[f"{k}_cost_usd"] = r[f"{k}_hours"] * r["rate_usd"]
    return rows


def total(rows, key):
    return sum(r[key] for r in rows)


def by(rows, key):
    out = defaultdict(list)
    for r in rows:
        out[r[key]].append(r)
    return dict(out)


def margin_bridge(rows):
    """Target margin, less each named cause, equals actual margin. It must close."""
    return {
        "target": total(rows, "target_margin_usd"),
        "scope": -total(rows, "scope_cost_usd"),
        "creep": -total(rows, "creep_cost_usd"),
        "rework": -total(rows, "rework_cost_usd"),
        "actual": total(rows, "actual_margin_usd"),
    }


def commentary(rows, label):
    lines = []
    for eng, rs in by(rows, "engagement").items():
        r = rs[0]
        miss = r["margin_miss_usd"]
        if miss < MATERIALITY_USD:
            continue
        causes = {"scope": r["scope_cost_usd"], "creep": r["creep_cost_usd"],
                  "rework": r["rework_cost_usd"]}
        driver = max(causes, key=causes.get)
        fix = {"scope": "an estimating problem",
               "creep": "a contracting problem",
               "rework": "a quality problem"}[driver]
        lines.append((miss,
            f"- **{eng}** ({r['system']}, {r['segment']}): sold at "
            f"${r['price_usd']:,.0f} to earn {TARGET_MARGIN:.0%}, delivered at "
            f"{r['actual_margin_pct']:.0%}. ${miss:,.0f} of margin went to "
            f"{r['delivered_hours'] - r['quoted_hours']:,} unquoted hours, mostly "
            f"{driver} (${causes[driver]:,.0f}), which is {fix}."))
    lines.sort(key=lambda x: -x[0])
    head = [l for _, l in lines[:TOP_N]]
    tail = lines[TOP_N:]
    if tail:
        head.append(f"- {len(tail)} further engagements miss by less than the top "
                    f"five, ${sum(m for m, _ in tail):,.0f} in aggregate. In "
                    f"`engagements.csv`, not repeated here.")
    return head


def build_report(rows):
    rows = enrich(rows)
    quarters = sorted({r["quarter"] for r in rows})
    current = [r for r in rows if r["quarter"] == quarters[-1]]
    prior = [r for r in rows if r["quarter"] == quarters[0]]
    b = margin_bridge(current)
    price = total(current, "price_usd")

    o = []
    o.append("# Delivery margin on fixed-price integration work\n")
    o.append("Synthetic data, generated by `delivery_margin.py`. "
             "The method is the point, not the figures.\n")
    o.append(f"## Margin bridge, {quarters[-1]}\n")
    o.append("| Step | USD | % of contracted revenue |")
    o.append("|---|---:|---:|")
    o.append(f"| Margin as sold | {b['target']:,.0f} | {b['target']/price:.0%} |")
    o.append(f"| Scope, quoted work that ran long | {b['scope']:,.0f} | {b['scope']/price:.0%} |")
    o.append(f"| Creep, work never quoted | {b['creep']:,.0f} | {b['creep']/price:.0%} |")
    o.append(f"| Rework, done twice | {b['rework']:,.0f} | {b['rework']/price:.0%} |")
    o.append(f"| **Margin as delivered** | **{b['actual']:,.0f}** | **{b['actual']/price:.0%}** |")
    o.append(f"\nContracted revenue {price:,.0f}. The bridge closes to the dollar; "
             f"that is asserted in the self-check, not asserted by me.\n")

    pm = total(prior, "actual_margin_usd") / total(prior, "price_usd")
    cm = b["actual"] / price
    o.append(f"## Direction, {quarters[0]} to {quarters[-1]}\n")
    o.append(f"- Delivered margin {pm:.0%} to {cm:.0%} "
             f"({'improving' if cm > pm else 'deteriorating'})")
    o.append(f"- Hours delivered against hours quoted: "
             f"{total(current,'delivered_hours')/total(current,'quoted_hours'):.2f}x "
             f"this quarter, {total(prior,'delivered_hours')/total(prior,'quoted_hours'):.2f}x last\n")

    o.append(f"## Engagements worth a sentence, {quarters[-1]}\n")
    o.append(f"Materiality: ${MATERIALITY_USD:,} of margin missed.\n")
    lines = commentary(current, quarters[-1])
    o.extend(lines if lines else ["- Nothing clears materiality this quarter."])

    o.append("\n## Where the hours go, by system integrated\n")
    o.append("| System | Contracted | Delivered margin | Biggest cause |")
    o.append("|---|---:|---:|---|")
    for system, rs in sorted(by(current, "system").items()):
        p, m = total(rs, "price_usd"), total(rs, "actual_margin_usd")
        causes = {k: total(rs, f"{k}_cost_usd") for k in ("scope", "creep", "rework")}
        o.append(f"| {system} | {p:,.0f} | {m/p:.0%} | {max(causes, key=causes.get)} |")
    return "\n".join(o) + "\n", rows


def self_check():
    rows = enrich(sample_rows())
    for r in rows:
        assert r["delivered_hours"] == (r["quoted_hours"] + r["scope_hours"]
                                        + r["creep_hours"] + r["rework_hours"]), "hours must close"
        assert abs(r["actual_margin_usd"] - (r["target_margin_usd"]
                   - r["scope_cost_usd"] - r["creep_cost_usd"]
                   - r["rework_cost_usd"])) < 1e-6, "margin bridge must close per row"
    b = margin_bridge(rows)
    assert abs(b["target"] + b["scope"] + b["creep"] + b["rework"] - b["actual"]) < 1e-6, \
        "margin bridge must close in total"
    clean = enrich([dict(r, scope_hours=0, creep_hours=0, rework_hours=0)
                    for r in sample_rows()])
    cb = margin_bridge(clean)
    assert abs(cb["target"] - cb["actual"]) < 1e-6, "no unquoted hours, no margin miss"
    for r in clean:
        assert abs(r["actual_margin_pct"] - TARGET_MARGIN) < 0.02, \
            "a clean engagement must land on its target margin"
    c1 = commentary([r for r in rows if r["quarter"] == "2026-Q4"], "x")
    assert c1 == commentary([r for r in rows if r["quarter"] == "2026-Q4"], "x"), \
        "commentary must be deterministic"
    named = [l.split("**")[1] for l in c1 if "**" in l]
    assert len(named) <= TOP_N and named == sorted(
        named, key=lambda e: -next(r["margin_miss_usd"] for r in rows if r["engagement"] == e)), \
        "commentary must be capped and ordered by margin missed"
    print("self-check passed: hours close, margin bridge closes per row and in "
          "total, a clean engagement lands on target, commentary is capped and ordered")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    if ap.parse_args().test:
        self_check(); sys.exit(0)
    md, rows = build_report(sample_rows())
    open("report.md", "w").write(md)
    cols = ["engagement", "quarter", "segment", "system", "price_usd", "rate_usd",
            "quoted_hours", "delivered_hours", "scope_hours", "creep_hours",
            "rework_hours", "target_margin_usd", "actual_margin_usd",
            "margin_miss_usd", "actual_margin_pct"]
    with open("engagements.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in cols})
    print("wrote report.md and engagements.csv")
