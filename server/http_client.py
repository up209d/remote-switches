import urequests
import ujson
import gc

def ask_gemini(prompt: str, maxTokens: int, api_key: str, model: str = 'gemini-flash-latest') -> dict:
    """
    Ask a question to the Gemini API and return the response as a dictionary.

    Args:
        prompt (str): The question or prompt to send to the Gemini API.
        api_key (str): Your Gemini API key.
        model (str): The model to use for the request. Default is 'gemini-2.5-flash'.

    Returns:
        dict: The response from the Gemini API as a dictionary.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {
        "X-goog-api-key": f"{api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": maxTokens
        }
    }

    try:
        response = urequests.post(url, headers=headers, data=ujson.dumps(payload))
        if response.status_code == 200:
            data = response.json()
            print(f"Gemini API response: \n\n{data}\n\n")  # Debugging line
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return {"result": text, "tokenCount": data["usageMetadata"]["totalTokenCount"]}
        else:
            print(f"Error: Received status code {response.status_code}")
            return { "error": f"Received status code {response.status_code}"}
    except Exception as e:
        print(f"Exception occurred: {e}")
        return { "error": str(e) }
    finally:
        gc.collect()  # Clean up memory after the request
