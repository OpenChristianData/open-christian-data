"""Quick test to diagnose HF Inference API errors."""
import os
from huggingface_hub import InferenceClient

token = os.environ.get("HF_TOKEN", "")
print(f"Token found: {'yes' if token else 'NO'}")

client = InferenceClient(token=token)

try:
    resp = client.chat_completion(
        model="meta-llama/Llama-3.3-70B-Instruct",
        messages=[{"role": "user", "content": "Say: ok"}],
        max_tokens=10,
    )
    print("SUCCESS:", resp.choices[0].message.content)
except Exception as e:
    print(f"ERROR type: {type(e).__name__}")
    print(f"ERROR msg:  {e}")
