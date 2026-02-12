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
        """Fetches ALL debtors."""
        url = f"{self.base_url}/api/Debtor/GetDebtor/"
        payload = {"AccNo": []}
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200: return r.json()
        except Exception as e:
            print(f"Error fetching debtors: {e}")
        return None

    def get_debtor_details(self, keyword):
        """Finds a specific debtor and returns full details."""
        all_debtors = self.get_debtors()
        if not all_debtors: return None

        keyword = keyword.lower().strip()
        
        # 1. Try Exact Code Match
        for d in all_debtors:
            if d.get("AccNo", "").lower() == keyword:
                return d
                
        # 2. Try Partial Name Match
        for d in all_debtors:
            if keyword in d.get("CompanyName", "").lower():
                return d
        
        return None

    # --- FUNCTION 2: SALES DASHBOARD ---
    def get_sales_dashboard(self, specific_date=None):
        url = f"{self.base_url}/api/Invoice/GetInvoice"
        
        if specific_date:
            target_date_str = specific_date
            dt = datetime.strptime(specific_date, "%Y/%m/%d")
            prev_date_str = (dt - timedelta(days=1)).strftime("%Y/%m/%d")
        else:
            now = datetime.now()
            target_date_str = now.strftime("%Y/%m/%d")
            prev_date_str = (now - timedelta(days=1)).strftime("%Y/%m/%d")
        
        payload = {"DateFrom": prev_date_str, "DateTo": target_date_str}
        
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=15)
            if r.status_code == 200:
                data = r.json().get("ResultTable", [])
                stats = {
                    "sales": 0.0, "prev_sales": 0.0, "count": 0,
                    "top_product": "None", "top_qty": 0, "date": target_date_str
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
                    best = max(product_tally, key=product_tally.get)
                    stats["top_product"] = best
                    stats["top_qty"] = product_tally[best]
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
                            first = item["ItemDTL"][0]
                            qty = first.get("BalQty", first.get("Qty", 0))
                            uom = first.get("UOM", "UNIT")
                        matches.append({"code": item.get("ItemCode"), "desc": item.get("Description"), "qty": qty, "uom": uom})
                        if len(matches) >= 5: break
                return matches
        except Exception as e:
            print(f"Error fetching stock: {e}")
        return None

ac_service = AutoCountService()

# ==========================================
# PART 2: AI BRAIN (UPDATED FOR NEW TASKS)
# ==========================================
def ask_ai_intent(user_text):
    print(f"\n🧠 AI Processing: '{user_text}'...")
    system_prompt = """
    You are an API Router for AutoCount Accounting.
    
    Functions:
    - get_debtors: "Who owes money?", "List debtors", "Outstanding balance"
    - top_debtors: "Who are the top 3 debtors?", "Highest outstanding", "Biggest bad payers", "Who owes the most?"
    - debtor_info: "Give me details for [Name]", "Address for [Name]", "Contact info for [Code]", "Check customer [Name]"
    - get_sales: "Sales today", "Sales for Jan 29", "Revenue report"
    - compare_sales: "Compare sales for Jan 29 and Aug 12"
    - check_stock: "Check stock for iPhone", "Inventory for [Item]"
    
    RULES:
    1. If user asks for details/address/phone of a SPECIFIC customer, return: debtor_info: [Name]
    2. If user asks for TOP/HIGHEST debtors, return: top_debtors
    3. If user compares dates, return: compare_sales: Date1 | Date2
    4. Otherwise, use standard function names.
    5. NEVER return JSON.
    """
    try:
        response = ollama.chat(model="deepseek-r1:8b", messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_text},
        ])
        reply = response['message']['content'].split('</think>')[-1].strip()
        reply = reply.replace("```json", "").replace("```", "").strip()
        print(f"👉 Intent: {reply}")
        return reply
    except:
        return "error"

# ==========================================
# PART 3: HANDLERS
# ==========================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    response = ask_ai_intent(user_text)
    
    # 1. TOP 3 OUTSTANDING (Task 1.2 A)
    if "top_debtors" in response:
        await update.message.reply_text("📉 Ranking debtors by highest debt...")
        data = ac_service.get_debtors()
        if data:
            # Sort by Balance (Descending)
            sorted_debtors = sorted(data, key=lambda x: float(x.get('Balance', x.get('Outstanding', 0.0))), reverse=True)
            top_3 = sorted_debtors[:3]
            
            msg = "🏆 **Top 3 Outstanding Customers**\n━━━━━━━━━━━━━━━━━━\n"
            for i, item in enumerate(top_3, 1):
                bal = float(item.get('Balance', item.get('Outstanding', 0.0)))
                phone = item.get('Phone1', 'No Phone')
                msg += f"{i}. **{item.get('CompanyName')}**\n   💰 RM {bal:,.2f}\n   📞 {phone}\n\n"
            
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("✅ No outstanding debtors found.")

    # 2. CUSTOMER INFO LOOKUP (Task 1.2 B)
    elif "debtor_info" in response:
        keyword = response.split(":", 1)[-1].strip()
        if not keyword:
            await update.message.reply_text("❓ Which customer?")
            return

        await update.message.reply_text(f"📇 Searching profile for '{keyword}'...")
        item = ac_service.get_debtor_details(keyword)
        
        if item:
            bal = float(item.get('Balance', item.get('Outstanding', 0.0)))
            # Build Address
            addr = ", ".join(filter(None, [item.get(f'InvAddr{i}') for i in range(1, 5)]))
            
            msg = (
                f"👤 **Customer Profile**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🏢 **{item.get('CompanyName')}**\n"
                f"🆔 Code: `{item.get('AccNo')}`\n"
                f"💰 Balance: **RM {bal:,.2f}**\n"
                f"💳 Limit: RM {item.get('CreditLimit', 0):,.2f}\n"
                f"📝 Term: {item.get('DisplayTerm', 'Net 30')}\n\n"
                f"📍 **Address**\n{addr}\n\n"
                f"📞 **Contact**\n"
                f"• Phone: {item.get('Phone1', 'N/A')}\n"
                f"• Fax: {item.get('Fax1', 'N/A')}\n"
                f"• Contact: {item.get('Attention', 'N/A')}"
            )
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Could not find customer matching '{keyword}'.")

    # 3. EXISTING FUNCTIONS
    elif "get_sales" in response:
        # Single Date Sales
        date_str = response.split(":", 1)[-1].strip()
        target_date = datetime.now().strftime("%Y/%m/%d") if ("latest" in date_str or not date_str) else date_str.replace("-", "/")
            
        await update.message.reply_text(f"📆 Fetching sales for {target_date}...")
        data = ac_service.get_sales_dashboard(target_date)
        if data:
            diff = data['sales'] - data['prev_sales']
            icon = "📈" if diff >= 0 else "📉"
            top_prod = f"{data['top_product']} ({data['top_qty']} units)" if data['top_product'] != "None" else "None"
            msg = (
                f"📅 **Sales Pulse: {data['date']}**\n━━━━━━━━━━━━━━━━━━\n"
                f"💵 **Revenue:** RM {data['sales']:,.2f}\n   *({icon} RM {abs(diff):,.2f} vs Prev Day)*\n\n"
                f"🧾 **Invoices:** {data['count']}\n🏆 **Top Seller:** {top_prod}"
            )
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
             await update.message.reply_text("❌ No data.")

    elif "compare_sales" in response:
        # Comparison
        try:
            d1, d2 = [d.strip().replace("-","/") for d in response.split(":", 1)[-1].split("|")]
            await update.message.reply_text(f"⚖️ Comparing **{d1}** vs **{d2}**...")
            s1 = ac_service.get_sales_dashboard(d1)
            s2 = ac_service.get_sales_dashboard(d2)
            if s1 and s2:
                diff = s1['sales'] - s2['sales']
                icon = "🟢" if diff >= 0 else "🔴"
                msg = (
                    f"⚔️ **Sales Showdown**\n━━━━━━━━━━━━━━━━━━\n"
                    f"📅 **{d1}**: RM {s1['sales']:,.2f}\n"
                    f"📅 **{d2}**: RM {s2['sales']:,.2f}\n"
                    f"━━━━━━━━━━━━━━━━━━\n**Diff:** {icon} RM {abs(diff):,.2f}"
                )
                await update.message.reply_text(msg, parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ Comparison failed.")
        except:
             await update.message.reply_text("⚠️ Dates invalid.")

    elif "check_stock" in response:
        keyword = response.split(":", 1)[-1].strip()
        if keyword:
            await update.message.reply_text(f"🔎 Searching stock for '{keyword}'...")
            items = ac_service.check_stock(keyword)
            if items:
                msg = f"📦 **Stock: '{keyword}'**\n"
                for i in items:
                    msg += f"🔹 `{i['code']}`: {i['desc']}\n   👉 **{i['qty']} {i['uom']}**\n"
                await update.message.reply_text(msg, parse_mode='Markdown')
            else:
                await update.message.reply_text(f"❌ No items found.")
        else:
             await update.message.reply_text("📦 Item name?")
             
    elif "get_debtors" in response:
        await update.message.reply_text("🔍 Fetching all debtors...")
        data = ac_service.get_debtors()
        if data:
            msg = "📊 **Debtor Report**\n"
            for item in data[:8]:
                bal = float(item.get('Balance', item.get('Outstanding', 0.0)))
                if bal > 0: msg += f"🔹 {item.get('CompanyName')}: RM {bal:,.2f}\n"
            await update.message.reply_text(msg, parse_mode='Markdown')

    else:
        await update.message.reply_text("🤖 I can help with:\n1. Top Debtors\n2. Customer Details\n3. Sales\n4. Stock")

if __name__ == '__main__':
    TELEGRAM_TOKEN = "8274589592:AAHJgltCVJ_s4VwQoLRpFvsNJJc-M0ycs6k"
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("🚀 AutoCount AI Agent is Running...")
    app.run_polling()