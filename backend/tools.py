import json
from datetime import datetime
from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "seller.json"


def load_seller():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def percent_change(old_value, new_value):
    if old_value == 0:
        return 0.0
    change = (new_value - old_value) / old_value * 100
    return round(change, 1)


def spoken_rupees(amount):
    amount = int(round(amount))
    if amount >= 100000:
        lakh = amount / 100000
        text = ("%.2f" % lakh).rstrip("0").rstrip(".")
        return text + " lakh rupees"
    if amount >= 1000:
        thousand = amount / 1000
        text = ("%.1f" % thousand).rstrip("0").rstrip(".")
        return text + " thousand rupees"
    return str(amount) + " rupees"


def written_rupees(amount):
    amount = int(round(amount))
    digits = str(amount)
    if len(digits) <= 3:
        return "Rs " + digits
    last_three = digits[-3:]
    rest = digits[:-3]
    parts = []
    while len(rest) > 2:
        parts.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        parts.insert(0, rest)
    return "Rs " + ",".join(parts) + "," + last_three


def now_text():
    return datetime.now().strftime("%H:%M:%S")


def add_action(session, kind, text):
    entry = {"time": now_text(), "kind": kind, "text": text}
    session["actions"].append(entry)
    return entry


def get_seller_snapshot(session):
    seller = load_seller()
    last = seller["metrics"]["last_month"]
    this = seller["metrics"]["this_month"]
    return {
        "seller_name": seller["seller_name"],
        "business_name": seller["business_name"],
        "category": seller["category"],
        "last_month": last,
        "this_month": this,
        "sales_last_month_spoken": spoken_rupees(last["sales"]),
        "sales_this_month_spoken": spoken_rupees(this["sales"]),
        "sales_change_percent": percent_change(last["sales"], this["sales"]),
        "orders_change_percent": percent_change(last["orders"], this["orders"]),
    }


def cancelled_orders(orders, rate):
    return int(round(orders * rate / 100))


def analyze_decline(session):
    seller = load_seller()
    last = seller["metrics"]["last_month"]
    this = seller["metrics"]["this_month"]
    extra = seller["assumptions"]

    sales_change = percent_change(last["sales"], this["sales"])
    orders_change = percent_change(last["orders"], this["orders"])
    price_change = percent_change(last["avg_selling_price"], this["avg_selling_price"])
    cancel_change_points = this["cancellation_rate"] - last["cancellation_rate"]
    oos_multiple = round(this["out_of_stock_products"] / last["out_of_stock_products"], 1)

    newly_orders = 0
    newly_count = 0
    for product in extra["out_of_stock_products"]:
        if product["newly_out_of_stock"]:
            newly_orders = newly_orders + product["last_month_orders"]
            newly_count = newly_count + 1
    newly_share = round(newly_orders / last["orders"] * 100, 1)

    last_cancelled = cancelled_orders(last["orders"], last["cancellation_rate"])
    this_cancelled = cancelled_orders(this["orders"], this["cancellation_rate"])
    extra_cancelled = int(round(this["orders"] * cancel_change_points / 100))
    last_realised = (last["orders"] - last_cancelled) * last["avg_selling_price"]
    this_realised = (this["orders"] - this_cancelled) * this["avg_selling_price"]
    realised_change = percent_change(last_realised, this_realised)

    causes = [
        {
            "rank": 1,
            "cause": "stock_outs",
            "confidence": "high",
            "evidence": [
                "Out-of-stock products rose from %d to %d, which is %s times more."
                % (last["out_of_stock_products"], this["out_of_stock_products"], oos_multiple),
                "%d products newly went out of stock. They produced %d of last month's %d orders (%s percent)."
                % (newly_count, newly_orders, last["orders"], newly_share),
            ],
        },
        {
            "rank": 2,
            "cause": "cancellations",
            "confidence": "high",
            "evidence": [
                "Cancellation rate rose from %d percent to %d percent."
                % (last["cancellation_rate"], this["cancellation_rate"]),
                "That is about %d extra cancelled orders this month." % extra_cancelled,
                "In the assumed data, %d percent of cancellations are because stock was unavailable."
                % extra["cancellation_reasons_this_month"]["stock_unavailable"],
            ],
        },
        {
            "rank": 3,
            "cause": "low_visibility",
            "confidence": "unknown",
            "evidence": [
                "Listings that are out of stock usually lose search visibility.",
                "No data on ads, ratings or search ranking was provided, so ask the seller.",
            ],
        },
        {
            "rank": 4,
            "cause": "pricing",
            "confidence": "low",
            "evidence": [
                "Average selling price did not change, it stayed at %d rupees." % this["avg_selling_price"],
                "Competitor prices are not in the data, so ask if the seller changed prices or discounts.",
            ],
        },
    ]

    return {
        "sales_change_percent": sales_change,
        "orders_change_percent": orders_change,
        "price_change_percent": price_change,
        "cancellation_change_points": cancel_change_points,
        "out_of_stock_multiple": oos_multiple,
        "cancelled_orders_last_month": last_cancelled,
        "cancelled_orders_this_month": this_cancelled,
        "realised_revenue_last_month_spoken": spoken_rupees(last_realised),
        "realised_revenue_this_month_spoken": spoken_rupees(this_realised),
        "realised_revenue_change_percent": realised_change,
        "assumption": "Sales equals orders times average selling price, and cancelled orders reduce realised revenue.",
        "ranked_causes": causes,
        "suggested_questions": [
            "Which products ran out, and when can you restock them?",
            "Why are orders getting cancelled, is it stock or late dispatch?",
            "Did you change prices, discounts or ads recently?",
        ],
    }


def get_oos_products(session, top_n=5):
    seller = load_seller()
    last_orders = seller["metrics"]["last_month"]["orders"]
    products = []
    for product in seller["assumptions"]["out_of_stock_products"]:
        if product["newly_out_of_stock"]:
            products.append(product)
    products.sort(key=lambda item: item["last_month_orders"], reverse=True)
    try:
        top_n = int(top_n)
    except (TypeError, ValueError):
        top_n = 5
    if top_n < 1:
        top_n = 1
    if top_n > len(products):
        top_n = len(products)
    chosen = products[:top_n]
    covered = 0
    lead_total = 0
    names = []
    for product in chosen:
        covered = covered + product["last_month_orders"]
        lead_total = lead_total + product["restock_lead_days"]
        names.append(product["name"])
    share = round(covered / last_orders * 100, 1)
    average_lead = round(lead_total / len(chosen), 1)
    return {
        "top_products": chosen,
        "product_names": names,
        "orders_covered": covered,
        "share_of_last_month_orders_percent": share,
        "average_restock_lead_days": average_lead,
        "note": "These are the newly out-of-stock products with the most orders last month.",
    }


def get_cancellation_reasons(session):
    seller = load_seller()
    this = seller["metrics"]["this_month"]
    total = cancelled_orders(this["orders"], this["cancellation_rate"])
    shares = seller["assumptions"]["cancellation_reasons_this_month"]
    reasons = {}
    for reason in shares:
        reasons[reason] = {
            "percent": shares[reason],
            "orders": int(round(total * shares[reason] / 100)),
        }
    return {
        "total_cancelled_orders": total,
        "reasons": reasons,
        "assumption": "The reason split is mock data added for this exercise.",
    }


def estimate_impact(session, action, top_n=5):
    seller = load_seller()
    this = seller["metrics"]["this_month"]
    price = this["avg_selling_price"]
    extra = seller["assumptions"]
    action = str(action)

    if action == "restock_top_products":
        info = get_oos_products(session, top_n)
        recovery = extra["recovery_rate_after_restock"]
        orders = int(round(info["orders_covered"] * recovery))
        sales = orders * price
        return {
            "action": action,
            "estimated_extra_orders_per_month": orders,
            "estimated_extra_sales_per_month": sales,
            "estimated_extra_sales_spoken": spoken_rupees(sales),
            "confidence": "medium",
            "assumption": "About %d percent of last month's orders for these products come back after restocking."
            % int(recovery * 100),
        }

    if action == "reduce_cancellations":
        target_rate = seller["metrics"]["last_month"]["cancellation_rate"]
        orders = int(round(this["orders"] * (this["cancellation_rate"] - target_rate) / 100))
        sales = orders * price
        return {
            "action": action,
            "estimated_extra_orders_per_month": orders,
            "estimated_extra_sales_per_month": sales,
            "estimated_extra_sales_spoken": spoken_rupees(sales),
            "confidence": "medium",
            "assumption": "Cancellation rate returns to last month's %d percent." % target_rate,
        }

    if action == "set_low_stock_alerts":
        return {
            "action": action,
            "estimated_extra_orders_per_month": None,
            "confidence": "qualitative",
            "assumption": "This prevents repeat stock-outs, so there is no separate number.",
        }

    if action == "improve_listings_and_ads":
        return {
            "action": action,
            "estimated_extra_orders_per_month": None,
            "confidence": "low",
            "assumption": "No ads, rating or ranking data was provided, so it cannot be estimated.",
        }

    return {"error": "Unknown action. Use restock_top_products, reduce_cancellations, set_low_stock_alerts or improve_listings_and_ads."}


def create_task(session, title, due_in_days=2, owner="seller"):
    try:
        due_in_days = int(due_in_days)
    except (TypeError, ValueError):
        due_in_days = 2
    text = "%s (owner: %s, due in %d days)" % (title, owner, due_in_days)
    add_action(session, "task", text)
    return {"status": "created", "task": text}


def schedule_followup(session, hours=48, reason="Check restock and cancellations"):
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        hours = 48
    text = "Follow-up call in %d hours: %s" % (hours, reason)
    add_action(session, "followup", text)
    return {"status": "scheduled", "when": "in %d hours" % hours, "reason": reason}


def send_summary(session, channel="whatsapp"):
    allowed = ["whatsapp", "sms", "email"]
    channel = str(channel).lower()
    if channel not in allowed:
        channel = "whatsapp"
    text = "Call summary sent by %s (mock)" % channel
    add_action(session, "message", text)
    return {"status": "sent", "channel": channel, "mock": True}


def escalate_to_human(session, reason="Seller asked for a human"):
    text = "Escalated to a human key account manager: %s" % reason
    add_action(session, "escalation", text)
    return {"status": "escalated", "reason": reason}


def finish_call(session, issues, recommendations, next_steps):
    def clean(items):
        result = []
        if isinstance(items, str):
            items = [items]
        if not isinstance(items, list):
            return result
        for item in items:
            result.append(str(item))
        return result

    summary = {
        "issues": clean(issues),
        "recommendations": clean(recommendations),
        "next_steps": clean(next_steps),
    }
    session["summary"] = summary
    session["finished"] = True
    add_action(session, "summary", "Call summary recorded")
    return {"status": "recorded", "summary": summary}


TOOLS = {
    "get_seller_snapshot": {
        "fn": get_seller_snapshot,
        "description": "Get this month versus last month numbers for the seller: sales, orders, cancellation rate, average selling price and out-of-stock products.",
        "parameters": {"type": "object", "properties": {}},
    },
    "analyze_decline": {
        "fn": analyze_decline,
        "description": "Analyse why sales dropped. Returns percentage changes, ranked likely causes with evidence and confidence, and suggested questions.",
        "parameters": {"type": "object", "properties": {}},
    },
    "get_oos_products": {
        "fn": get_oos_products,
        "description": "List the newly out-of-stock products with the most orders last month, and how much of last month's orders they covered.",
        "parameters": {
            "type": "object",
            "properties": {"top_n": {"type": "integer", "description": "How many products to return, default 5"}},
        },
    },
    "get_cancellation_reasons": {
        "fn": get_cancellation_reasons,
        "description": "Get the number of cancelled orders this month and the split by reason.",
        "parameters": {"type": "object", "properties": {}},
    },
    "estimate_impact": {
        "fn": estimate_impact,
        "description": "Estimate the extra orders and sales from one action. Use before recommending it.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "One of restock_top_products, reduce_cancellations, set_low_stock_alerts, improve_listings_and_ads",
                },
                "top_n": {"type": "integer", "description": "Number of top products for restock_top_products, default 5"},
            },
            "required": ["action"],
        },
    },
    "create_task": {
        "fn": create_task,
        "description": "Create a task for the seller or the support team after the seller agrees to an action.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "due_in_days": {"type": "integer"},
                "owner": {"type": "string", "description": "seller or snapdeal_team"},
            },
            "required": ["title"],
        },
    },
    "schedule_followup": {
        "fn": schedule_followup,
        "description": "Schedule a follow-up call with the seller.",
        "parameters": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "Hours from now, usually 48"},
                "reason": {"type": "string"},
            },
        },
    },
    "send_summary": {
        "fn": send_summary,
        "description": "Send the call summary to the seller by whatsapp, sms or email.",
        "parameters": {
            "type": "object",
            "properties": {"channel": {"type": "string", "description": "whatsapp, sms or email"}},
        },
    },
    "escalate_to_human": {
        "fn": escalate_to_human,
        "description": "Hand the seller to a human key account manager if they ask for one or are very upset.",
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
        },
    },
    "finish_call": {
        "fn": finish_call,
        "description": "Record the final summary at the end of the call: key issues, recommendations and next steps.",
        "parameters": {
            "type": "object",
            "properties": {
                "issues": {"type": "array", "items": {"type": "string"}},
                "recommendations": {"type": "array", "items": {"type": "string"}},
                "next_steps": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["issues", "recommendations", "next_steps"],
        },
    },
}


def run_tool(session, name, args):
    if name not in TOOLS:
        return {"error": "Unknown tool: %s" % name}
    if not isinstance(args, dict):
        args = {}
    function = TOOLS[name]["fn"]
    try:
        return function(session, **args)
    except TypeError as error:
        return {"error": "Bad arguments for %s: %s" % (name, error)}
    except Exception as error:
        return {"error": "Tool %s failed: %s" % (name, error)}
