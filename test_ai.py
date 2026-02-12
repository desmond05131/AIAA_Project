import ollama
import json

# The model you downloaded
MODEL_NAME = "deepseek-r1:8b"

def ask_ai_intent(user_text):
    print(f"\n🧠 Thinking about: '{user_text}'...")
    
    # 1. The Prompt: We teach the AI to be a "Router"
    # We tell it: "Don't chat. Just tell me which function to run."
    system_prompt = """
    You are an API Router for an Accounting System.
    Your job is to map User Questions to specific Function Names.
    
    Available Functions:
    - get_debtors: For questions about money owed, debtors, outstanding balance, or bad payers.
    - check_stock: For questions about inventory, item quantity, or stock levels.
    - none: For casual greetings (hi, hello) or unrelated topics.

    RULES:
    1. Reply ONLY with the function name.
    2. Do NOT explain your reasoning.
    3. Do NOT output markdown or <think> tags.
    """

    try:
        # 2. Call Ollama
        response = ollama.chat(model=MODEL_NAME, messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_text},
        ])
        
        # 3. Clean the response (DeepSeek R1 often includes <think> tags)
        raw_reply = response['message']['content']
        
        # Remove <think> sections if present
        clean_reply = raw_reply.split('</think>')[-1].strip()
        
        return clean_reply
        
    except Exception as e:
        return f"Error: {e}"

# TEST LOOP
if __name__ == "__main__":
    test_phrases = [
        "Who owes us money?",
        "Do we have stock for iPhone?",
        "Good morning",
        "List the bad payers"
    ]
    
    print(f"🤖 Testing Model: {MODEL_NAME}")
    print("--------------------------------")
    
    for phrase in test_phrases:
        intent = ask_ai_intent(phrase)
        print(f"User: '{phrase}'")
        print(f"AI Router Decision: -> {intent}")
        print("--------------------------------")