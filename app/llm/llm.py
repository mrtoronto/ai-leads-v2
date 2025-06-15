import requests
from app.local_settings import OPENAI_API_KEY_GPT4, ANTHROPIC_API_KEY

def _llm(messages, model_name='gpt-4o-mini', temp=0.1):
    """Make an LLM API call - supports both OpenAI and Anthropic models"""
    
    # Define model categories
    openai_models = ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1']
    anthropic_models = ['claude-opus-4-20250514', 'claude-sonnet-4-20250514']
    
    if model_name in openai_models:
        return _call_openai(messages, model_name, temp)
    elif model_name in anthropic_models:
        return _call_anthropic(messages, model_name, temp)
    else:
        print(f'Unknown model: {model_name}. Defaulting to gpt-4o-mini.')
        return _call_openai(messages, 'gpt-4o-mini', temp)

def _call_openai(messages, model_name, temp):
    """Make an OpenAI API call"""
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
        print(f'OpenAI API Error: {response.status_code} - {response.json()}')
        return None

def _call_anthropic(messages, model_name, temp):
    """Make an Anthropic API call"""
    headers = {
        'x-api-key': ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json'
    }
    
    # Convert OpenAI format messages to Anthropic format
    anthropic_messages = []
    for msg in messages:
        if msg['role'] == 'system':
            # Anthropic handles system messages differently - we'll prepend to first user message
            continue
        anthropic_messages.append({
            'role': msg['role'],
            'content': msg['content']
        })
    
    # If there was a system message, prepend it to the first user message
    system_content = None
    for msg in messages:
        if msg['role'] == 'system':
            system_content = msg['content']
            break
    
    if system_content and anthropic_messages and anthropic_messages[0]['role'] == 'user':
        anthropic_messages[0]['content'] = f"{system_content}\n\n{anthropic_messages[0]['content']}"
    
    data = {
        'model': model_name,
        'max_tokens': 8000,
        'temperature': temp,
        'messages': anthropic_messages
    }
    
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=data
    )
    
    if response.status_code == 200:
        return response.json()['content'][0]['text']
    else:
        print(f'Anthropic API Error: {response.status_code} - {response.json()}')
        return None