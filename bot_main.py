import logging
import requests
import json
import ollama
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# ==========================================
# PART 1: AUTOCOUNT BRIDGE
# ==========================================
class AutoCountService:
    def __init__(self):
        self.base_url = "http://localhost:8015"
        self.user_id = "ADMIN"
        self.password = "ADMIN"
        self.token = "FK98DL-2AAAAA-AAAAAA-AAAAAA-ABLUB5-YR6ABK-DVAC8P-F5BQ7G"
        self.auth_key = None

    def login(self):
        """Authenticates and retrieves the JWT Token."""
        url = f"{self.base_url}/api/v3/Login"
        payload = {"UserID": self.user_id, "Password": self.password, "Token": self.token}
        try:
            r = requests.post(url, json=payload, timeout=5)
            if r.status_code == 200 and len(r.json()) > 0:
                self.auth_key = r.json()[0].get("JWTToken")
                print("✅ [AutoCount] Login Successful")
                return True
        except Exception as e:
            print(f"❌ [AutoCount] Connection Error: {e}")
        return False

    def _get_headers(self):
        if not self.auth_key: self.login()
        return {"Content-Type": "application/json", "Authorization": self.auth_key}

    # --- FUNCTION 1: FINANCIALS (DEBTORS) ---
    def get_debtors(self):
        url = f"{self.base_url}/api/Debtor/GetDebtor/"
        payload = {"AccNo": []}
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200: return r.json()
        except Exception as e:
            print(f"Error fetching debtors: {e}")
        return None

    # --- FUNCTION 2: SALES DASHBOARD ---
    def get_sales_dashboard(self, specific_date=None):
        url = f"{self.base_url}/api/Invoice/GetInvoice"
        
        # Determine Date Logic
        if specific_date:
            # If user asks for specific date (e.g. "2026/01/29")
            target_date_str = specific_date
            # For comparison stats, we usually compare vs the day before target
            dt = datetime.strptime(specific_date, "%Y/%m/%d")
            prev_date_str = (dt - timedelta(days=1)).strftime("%Y/%m/%d")
        else:
            # Default to Today vs Yesterday
            now = datetime.now()
            target_date_str = now.strftime("%Y/%m/%d")
            prev_date_str = (now - timedelta(days=1)).strftime("%Y/%m/%d")
        
        # Request Data
        payload = {"DateFrom": prev_date_str, "DateTo": target_date_str}
        
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=15)
            if r.status_code == 200:
                data = r.json().get("ResultTable", [])
                
                stats = {
                    "sales": 0.0,
                    "prev_sales": 0.0,
                    "count": 0,
                    "top_product": "None",
                    "top_qty": 0,
                    "date": target_date_str
                }
                
                product_tally = {}

                for inv in data:
                    if inv.get("Cancelled") == "T": continue
                    
                    doc_date = inv.get("DocDate", "")[:10].replace("-", "/")
                    amount = float(inv.get("FinalTotal", inv.get("NetTotal", 0.0)))

                    if doc_date == target_date_str:
                        stats["sales"] += amount
                        stats["count"] += 1
                        if "IVDTL" in inv:
                            for item in inv["IVDTL"]:
                                code = item.get("ItemCode")
                                qty = item.get("Qty", 0)
                                desc = item.get("Description", code)
                                if code:
                                    product_tally[desc] = product_tally.get(desc, 0) + qty
                                    
                    elif doc_date == prev_date_str:
                        stats["prev_sales"] += amount

                if product_tally:
                    best_seller = max(product_tally, key=product_tally.get)
                    stats["top_product"] = best_seller
                    stats["top_qty"] = product_tally[best_seller]

                return stats
        except Exception as e:
            print(f"Error fetching sales: {e}")
        return None

    # --- FUNCTION 3: STOCK CHECKER ---
    def check_stock(self, keyword):
        url = f"{self.base_url}/api/V2/Item/GetItem"
        payload = {"ItemCode": [], "IncludeBatchBal": True}
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json().get("ResultTable", [])
                matches = []
                keyword = keyword.lower()
                for item in data:
                    code = item.get("ItemCode", "").lower()
                    desc = item.get("Description", "").lower()
                    if keyword in code or keyword in desc:
                        qty = 0
                        uom = "UNIT"
                        if "ItemDTL" in item and len(item["ItemDTL"]) > 0:
                            first_dtl = item["ItemDTL"][0]
                            qty = first_dtl.get("BalQty", first_dtl.get("Qty", 0))
                            uom = first_dtl.get("UOM", "UNIT")
                        matches.append({"code": item.get("ItemCode"), "desc": item.get("Description"), "qty": qty, "uom": uom})
                        if len(matches) >= 5: break
                return matches
        except Exception as e:
            print(f"Error fetching stock: {e}")
        return None

ac_service = AutoCountService()

# ==========================================
# PART 2: AI BRAIN (RE-TRAINED)
# ==========================================
def ask_ai_intent(user_text):
    print(f"\n🧠 AI Processing: '{user_text}'...")
    system_prompt = """
    You are an API Router for AutoCount Accounting.
    
    Functions:
    - get_debtors: "Who owes money?", "List debtors"
    - get_sales: "Sales today", "Sales for Jan 29", "Check latest sales"
    - compare_sales: "Compare sales for Jan 29 and Aug 12", "Compare today vs yesterday"
    - check_stock: "Check stock for iPhone"
    - none: Casual chat.

    RULES:
    1. For single dates, return: get_sales: YYYY-MM-DD
       (If user says "latest", return: get_sales: latest)
    
    2. For COMPARISONS, return: compare_sales: YYYY-MM-DD | YYYY-MM-DD
       Example: "Compare Jan 1 and Feb 1" -> compare_sales: 2026-01-01 | 2026-02-01
    
    3. NEVER return JSON. NEVER return markdown code blocks. Just the string.
    """
    try:
        response = ollama.chat(model="deepseek-r1:8b", messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_text},
        ])
        reply = response['message']['content'].split('</think>')[-1].strip()
        
        # Clean up if AI still sends markdown code blocks
        reply = reply.replace("```json", "").replace("```", "").strip()
        
        print(f"👉 Intent: {reply}")
        return reply
    except:
        return "error"

# ==========================================
# PART 3: HANDLERS (NEW LOGIC)
# ==========================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    response = ask_ai_intent(user_text)
    
    # 1. DEBTORS
    if "get_debtors" in response:
        await update.message.reply_text("🔍 Checking outstanding balances...")
        data = ac_service.get_debtors()
        if data:
            msg = "📊 **Debtor Aging Summary**\n"
            total = 0.0
            for item in data[:10]:
                bal = float(item.get('Balance', item.get('Outstanding', 0.0)))
                if bal > 0:
                    msg += f"🔹 {item.get('CompanyName')}: RM {bal:,.2f}\n"
                    total += bal
            msg += f"\n💰 **Total Visible: RM {total:,.2f}**"
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("✅ No outstanding debtors.")

    # 2. COMPARISON MODE (NEW!)
    elif "compare_sales" in response:
        # Expected format: compare_sales: 2026-01-29 | 2025-08-12
        try:
            dates_part = response.split(":", 1)[-1].strip()
            date_a, date_b = [d.strip() for d in dates_part.split("|")]
            
            # Normalize dates (Replace - with /)
            date_a = date_a.replace("-", "/")
            date_b = date_b.replace("-", "/")
            
            await update.message.reply_text(f"⚖️ Comparing **{date_a}** vs **{date_b}**...")
            
            # Fetch data twice
            stats_a = ac_service.get_sales_dashboard(date_a)
            stats_b = ac_service.get_sales_dashboard(date_b)
            
            if stats_a and stats_b:
                diff = stats_a['sales'] - stats_b['sales']
                icon = "🟢" if diff >= 0 else "🔴"
                
                msg = (
                    f"⚔️ **Sales Showdown**\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"📅 **{date_a}**: RM {stats_a['sales']:,.2f}\n"
                    f"📅 **{date_b}**: RM {stats_b['sales']:,.2f}\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"**Difference:** {icon} RM {abs(diff):,.2f}\n"
                )
                await update.message.reply_text(msg, parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ Could not fetch data for comparison.")
                
        except Exception as e:
            print(f"Comparison Error: {e}")
            await update.message.reply_text("⚠️ Could not process comparison dates.")

    # 3. SALES DASHBOARD (SINGLE DATE)
    elif "get_sales" in response:
        # Extract Date
        date_str = response.split(":", 1)[-1].strip()
        
        # Handle "latest" or empty
        if "latest" in date_str or not date_str:
            target_date = datetime.now().strftime("%Y/%m/%d")
        else:
            # Convert 2026-01-29 -> 2026/01/29
            target_date = date_str.replace("-", "/")

        await update.message.reply_text(f"📆 Fetching sales for {target_date}...")
        
        data = ac_service.get_sales_dashboard(target_date)
        
        if data:
            diff = data['sales'] - data['prev_sales']
            icon = "📈" if diff >= 0 else "📉"
            top_prod = f"{data['top_product']} ({data['top_qty']} units)" if data['top_product'] != "None" else "None"

            msg = (
                f"📅 **Sales Pulse: {data['date']}**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💵 **Revenue:** RM {data['sales']:,.2f}\n"
                f"   *({icon} RM {abs(diff):,.2f} vs Prev Day)*\n\n"
                f"🧾 **Invoices:** {data['count']}\n"
                f"🏆 **Top Seller:** {top_prod}"
            )
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ No data found.")

    # 4. STOCK
    elif "check_stock" in response:
        keyword = response.split(":", 1)[-1].strip()
        if keyword:
            await update.message.reply_text(f"🔎 Searching inventory for '{keyword}'...")
            items = ac_service.check_stock(keyword)
            if items:
                msg = f"📦 **Stock Results for '{keyword}'**\n"
                for i in items:
                    msg += f"🔹 `{i['code']}`: {i['desc']}\n   👉 **{i['qty']} {i['uom']}**\n"
                await update.message.reply_text(msg, parse_mode='Markdown')
            else:
                await update.message.reply_text(f"❌ No items found.")
        else:
            await update.message.reply_text("📦 What item?")

    else:
        await update.message.reply_text("🤖 I'm listening.")

if __name__ == '__main__':
    TELEGRAM_TOKEN = "8274589592:AAHJgltCVJ_s4VwQoLRpFvsNJJc-M0ycs6k"
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("🚀 AutoCount AI Agent is Running...")
    app.run_polling()