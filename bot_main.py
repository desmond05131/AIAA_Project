import logging
import requests
import json
import ollama
import re
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

    # --- FUNCTION 1: DEBTOR LIST (Flexible Limit) ---
    def get_debtors(self, limit=5):
        url = f"{self.base_url}/api/Debtor/GetDebtor/"
        payload = {"AccNo": []} 
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json()
                # Sort by Balance (Descending) to show highest debt first
                # We normalize field names (Balance vs Outstanding)
                sorted_data = sorted(
                    data, 
                    key=lambda x: float(x.get('Balance', x.get('Outstanding', 0.0))), 
                    reverse=True
                )
                return sorted_data[:limit]
        except Exception as e:
            print(f"Error fetching debtors: {e}")
        return None

    # --- FUNCTION 2: DEBTOR PROFILE (Detailed Lookup) ---
    def get_debtor_profile(self, keyword):
        url = f"{self.base_url}/api/Debtor/GetDebtor/"
        payload = {"AccNo": []} # Fetch all to search
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json()
                keyword = keyword.lower()
                
                for item in data:
                    name = item.get("CompanyName", "").lower()
                    code = item.get("AccNo", "").lower()
                    
                    if keyword in name or keyword in code:
                        return item # Return the specific dictionary
        except Exception as e:
            print(f"Error fetching profile: {e}")
        return None

    # --- FUNCTION 3: SALES DASHBOARD ---
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
                stats = {"sales": 0.0, "prev_sales": 0.0, "count": 0, "date": target_date_str}
                for inv in data:
                    if inv.get("Cancelled") == "T": continue
                    doc_date = inv.get("DocDate", "")[:10].replace("-", "/")
                    amount = float(inv.get("FinalTotal", inv.get("NetTotal", 0.0)))
                    if doc_date == target_date_str:
                        stats["sales"] += amount
                        stats["count"] += 1
                    elif doc_date == prev_date_str:
                        stats["prev_sales"] += amount
                return stats
        except:
            return None

    # --- FUNCTION 4: STOCK ---
    def check_stock(self, keyword):
        url = f"{self.base_url}/api/V2/Item/GetItem"
        payload = {"ItemCode": [], "IncludeBatchBal": True}
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json().get("ResultTable", [])
                matches = []
                for item in data:
                    if keyword.lower() in item.get("ItemCode", "").lower() or keyword.lower() in item.get("Description", "").lower():
                        qty = item.get("Qty", 0)
                        if "ItemDTL" in item and item["ItemDTL"]:
                            qty = item["ItemDTL"][0].get("BalQty", qty)
                        matches.append({"code": item.get("ItemCode"), "desc": item.get("Description"), "qty": qty})
                        if len(matches) >= 5: break
                return matches
        except:
            return None
            
ac_service = AutoCountService()

# ==========================================
# PART 2: AI BRAIN
# ==========================================
def ask_ai_intent(user_text):
    print(f"\n🧠 AI Processing: '{user_text}'...")
    system_prompt = """
    You are an AutoCount API Router. Map requests to these specific formats:
    
    1. DEBTORS (General List):
       - "Who owes money?" -> get_debtors: 5
       - "Top 10 debtors" -> get_debtors: 10
       - "List 3 bad payers" -> get_debtors: 3
    
    2. DEBTOR PROFILE (Specific Company):
       - "Info on Ali" -> get_debtor_profile: Ali
       - "Details for ABC Corp" -> get_debtor_profile: ABC Corp
       - "Look for Chew Choon" -> get_debtor_profile: Chew Choon
    
    3. SALES:
       - "Sales today" -> get_sales: latest
    
    4. STOCK:
       - "Check stock iPhone" -> check_stock: iPhone
    
    Reply ONLY with the formatted string. No JSON.
    """
    try:
        response = ollama.chat(model="deepseek-r1:8b", messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_text},
        ])
        reply = response['message']['content'].split('</think>')[-1].strip()
        reply = reply.replace("`", "").strip() # Clean cleanup
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
    
    # 1. TOP DEBTORS LIST
    if "get_debtors" in response:
        # Extract number (default to 5)
        try:
            limit = int(re.search(r'\d+', response).group())
        except:
            limit = 5
            
        await update.message.reply_text(f"📉 Listing Top {limit} Debtors...")
        data = ac_service.get_debtors(limit)
        
        if data:
            msg = f"🏆 **Top {len(data)} Outstanding Customers**\n━━━━━━━━━━━━━━━━━━\n"
            i = 1
            for item in data:
                bal = float(item.get('Balance', item.get('Outstanding', 0.0)))
                name = item.get('CompanyName')
                # Try to get phone
                phone = item.get('Phone1', item.get('Phone2', 'No Phone'))
                
                msg += f"{i}. {name}\n   💰 RM {bal:,.2f}\n   📞 {phone}\n\n"
                i += 1
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("✅ No data found.")

    # 2. SPECIFIC DEBTOR PROFILE (New!)
    elif "get_debtor_profile" in response:
        keyword = response.split(":", 1)[-1].strip()
        await update.message.reply_text(f"📇 Searching profile for '{keyword}'...")
        
        item = ac_service.get_debtor_profile(keyword)
        
        if item:
            # --- FIX: ADDRESS LOGIC ---
            addr_parts = [
                item.get('Address1'), 
                item.get('Address2'), 
                item.get('Address3'), 
                item.get('Address4'),
                item.get('PostCode'),
                item.get('AreaCode'),
                item.get('State')
            ]
            # Filter out None or empty strings and join them
            full_address = ", ".join([str(p) for p in addr_parts if p])
            if not full_address: full_address = "N/A"
            
            bal = float(item.get('Balance', item.get('Outstanding', 0.0)))
            limit = float(item.get('CreditLimit', 0.0))
            term = item.get('DisplayTerm', 'N/A')
            phone = item.get('Phone1', 'N/A')
            fax = item.get('Fax1', 'N/A')
            contact_person = item.get('Attention', 'N/A')
            
            msg = (
                f"👤 **Customer Profile**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🏢 **{item.get('CompanyName')}**\n"
                f"🆔 Code: `{item.get('AccNo')}`\n"
                f"💰 Balance: RM {bal:,.2f}\n"
                f"💳 Limit: RM {limit:,.2f}\n"
                f"📝 Term: {term}\n\n"
                f"📍 **Address**\n{full_address}\n\n"
                f"📞 **Contact**\n"
                f"• Phone: {phone}\n"
                f"• Fax: {fax}\n"
                f"• Contact: {contact_person}"
            )
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Customer '{keyword}' not found.")

    # 3. SALES
    elif "get_sales" in response:
        await update.message.reply_text("💰 Checking Today's Sales...")
        data = ac_service.get_sales_dashboard()
        if data:
            diff = data['sales'] - data['prev_sales']
            icon = "📈" if diff >= 0 else "📉"
            msg = (f"📅 **Sales: {data['date']}**\n"
                   f"💸 Revenue: RM {data['sales']:,.2f}\n"
                   f"   ({icon} RM {abs(diff):,.2f} vs Yesterday)")
            await update.message.reply_text(msg, parse_mode='Markdown')

    # 4. STOCK
    elif "check_stock" in response:
        keyword = response.split(":", 1)[-1].strip()
        items = ac_service.check_stock(keyword)
        if items:
            msg = ""
            for i in items:
                msg += f"📦 {i['desc']}: **{i['qty']}**\n"
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Item not found")
            
    else:
        await update.message.reply_text("🤖 I am ready.")

if __name__ == '__main__':
    TELEGRAM_TOKEN = "8274589592:AAHJgltCVJ_s4VwQoLRpFvsNJJc-M0ycs6k"
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("🚀 AutoCount AI Agent is Running...")
    app.run_polling()