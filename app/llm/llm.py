import requests
from app.local_settings import OPENAI_API_KEY_GPT4

def _llm(messages, model_name='gpt-4o-mini', temp=0.1):
    """Make an LLM API call"""
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {OPENAI_API_KEY_GPT4}'
    }
    
    data = {
        'model': model_name,
        'messages': messages,
        'max_tokens': 8000,
        'temperature': temp
    }
    
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=data
    )
    
    if response.status_code == 200:
        return response.json()['choices'][0]['message']['content']
    else:
        print(f'LLM Error: {response.status_code} - {response.json()}')
        return None