import os
import io
import time
import requests
import gspread
from datetime import datetime
from dotenv import load_dotenv
from prefect import flow, task
from huggingface_hub import InferenceClient
from PIL import Image

# 1. LOAD ENVIRONMENT VARIABLES
# Load variables from the .env file
load_dotenv()

# Retrieve sensitive keys safely
# Using .getenv() prevents crashing if the key is missing (returns None instead)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HF_TOKEN = os.getenv("HF_TOKEN")

def get_google_sheets():
    # 2. GOOGLE SHEETS SETUP
    # Authenticate using the service account JSON file
    gc = gspread.service_account("chatbot_key.json")

    # Open the specific Spreadsheet by name
    sh = gc.open("Image Prompt")

    # Define the specific worksheets (tabs) to work with
    ws_process = sh.worksheet("Process")
    ws_done = sh.worksheet("Done")

    return ws_process, ws_done

def get_hf_client():
    # 3. HUGGING FACE CLIENT SETUP
    # Initialize the client for image generation
    return InferenceClient(
        api_key=HF_TOKEN  # Using the variable defined above
    )

@task(name="Fetch Prompt", retries=3, retry_delay_seconds=5)
def get_prompt():
    """
    Fetches the first available prompt from the Google Sheet (Row 2).
    """
    print("🔍 Scanning the prompt queue...")

    try:
        ws_process, _ = get_google_sheets()

        # Check if there is data in the first column (Header + at least 1 data row)
        # We assume Row 1 is Header, Row 2 is Data.
        if len(ws_process.col_values(1)) > 1:
            
            # Fetch the prompt from Row 2, Column 1 (Index 0)
            prompt_text = ws_process.row_values(2)[0]

            print(f"✅ Target Acquired: '{prompt_text}'")
            return prompt_text

        else:
            # If the list is empty (only header exists)
            print("💤 Queue is empty. No missions for today.")
            return None

    except Exception as e:
        # If a connection error occurs (e.g., Google API down)
        # We re-raise the error so Prefect knows to RETRY this task.
        print(f"❌ Connection Error: {e}")
        # Raise a clean exception so Prefect knows to RETRY this task.
        raise Exception("Google Sheets Connection Failed")

@task(name="Generate Image", retries=3, retry_delay_seconds=5)
def generate_img(prompt: str):
    """
    Generates an image based on the text prompt using the Fal AI model.
    Returns the image as a Byte Array (in-memory) for Telegram transmission.
    """
    
    # 1. INPUT VALIDATION
    # Ensure the prompt is valid before calling the expensive API
    if prompt is None or prompt.strip() == "":
        print("❌ Error: Received an empty prompt.")
        # We raise a ValueError so the Main Flow knows this step failed
        raise ValueError("Prompt cannot be empty or None.")

    print(f"🎨 Generating Image for: '{prompt}'")

    try:
        client = get_hf_client()

        # 2. CALL GENERATION API
        # Sending request to Black Forest Labs FLUX.1 model
        image = client.text_to_image(
            prompt,
            model="stabilityai/stable-diffusion-xl-base-1.0",
        )

        # 3. OUTPUT VALIDATION
        # Safety check: Ensure the API actually returned an object
        if not image:
            raise ValueError("API returned an empty result (No Image).")

        # 4. IMAGE PROCESSING (IN-MEMORY)
        # Create a virtual file in RAM (BytesIO) to avoid saving to hard drive
        img_bytes_arr = io.BytesIO()
        
        # Save the PIL image into the buffer as PNG format
        image.save(img_bytes_arr, format="PNG")
        
        # Reset the cursor to the beginning of the file so it can be read later
        img_bytes_arr.seek(0)
        
        print("✅ Image generated and converted to bytes successfully.")
        return img_bytes_arr

    except Exception as e:
        # 5. SAFE ERROR HANDLING
        # We convert the error to a string for analysis but avoid printing the raw error
        # directly if possible, to prevent leaking sensitive tokens in logs.
        error_str = str(e).lower()

        # --- DETECT ERROR TYPE SAFELY ---

        # CASE 1: Authentication Error (Wrong Token)
        if "401" in error_str or "unauthorized" in error_str or "token" in error_str:
            clean_msg = "🔒 AUTH ERROR: Hugging Face Token is invalid or missing."
            print(clean_msg)
            # Critical error: Stop execution immediately.
            raise ValueError(clean_msg)

        # CASE 2: Rate Limit (Free tier limits)
        elif "429" in error_str:
            clean_msg = "⏳ RATE LIMIT: Hugging Face API limit reached. Please wait."
            print(clean_msg)
            # Raise exception to trigger Prefect retries.
            raise Exception(clean_msg)

        # CASE 3: Model Loading (Common in HF Inference API)
        # This usually resolves itself after a few seconds.
        elif "503" in error_str or "loading" in error_str:
            clean_msg = "🏗️ MODEL BUSY: The model is currently loading on Hugging Face servers."
            print(clean_msg)
            # Raise exception to trigger Prefect retries.
            raise Exception(clean_msg)

        # CASE 4: Network/Connection Errors
        elif "connection" in error_str or "max retries" in error_str:
            clean_msg = "❌ NETWORK ERROR: Failed to connect to Hugging Face API."
            print(clean_msg)
            # Raise exception to trigger Prefect retries.
            raise Exception(clean_msg)

        # CASE 5: API Key Quota / Credit Depleted (Business Logic)
        # This checks for specific billing error messages.
        elif "credit balance" in error_str or "depleted" in error_str:
            warning_msg = "💳 QUOTA EXCEEDED: Your Hugging Face credit balance is depleted. Purchase credits or upgrade to Pro."
            print(f"Status: {warning_msg}")
            
            # NOTE: We RETURN the warning string here instead of raising an exception.
            # This allows the Main Flow to catch this specific string and send it 
            # as a notification message to the Telegram user.
            return warning_msg

        # CASE 6: Unknown Error
        else:
            print("🔥 GENERATION FAILED: An unknown error occurred during image generation.")
            print("   (Raw error details hidden for security)")
            
            # Raise a generic exception to mark the task as Failed.
            raise Exception("Unknown Image Generation Error")

@task(name="Send to Telegram", retries=3, retry_delay_seconds=5)
def to_telegram(caption, img):
    """
    Sends the generated image and caption to the specified Telegram Chat.
    """
    
    # 1. CONSTRUCT API URL
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"

    # 2. PREPARE FILE PAYLOAD
    # We must send the file as a tuple: (filename, file_data, mime_type)
    # This tells requests how to format the binary data properly.
    files = {
        "photo": ("generated_image.png", img, "image/png")
    }

    # 3. PREPARE DATA PAYLOAD
    # Note: Telegram API keys are case-sensitive. Use 'chat_id', not 'CHAT_ID'.
    data = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "caption": caption
    }

    print(f"🚀 Sending image to Telegram Chat ID: {TELEGRAM_CHAT_ID}...")

    # 4. SEND REQUEST
    try:
        response = requests.post(url, files=files, data=data)
        
        # 5. VALIDATE RESPONSE
        if response.status_code == 200:
            print("✅ Success: Message delivered to Telegram!")
        else:
            # If the API returns an error (e.g., 400 Bad Request, 401 Unauthorized)
            print(f"❌ Telegram Refused: Status Code {response.status_code}")
            
            # CRITICAL: Raise an exception so Prefect knows this task FAILED.
            raise Exception(f"Telegram API Error: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Network Error sending to Telegram.")
        raise Exception("Telegram Connection Failed")

@task(name="Send Information to Telegram", retries=3, retry_delay_seconds=5)
def send_information(information):
    # 1. Validate Credentials
    if not TELEGRAM_TOKEN and not TELEGRAM_CHAT_ID:
        error_msg = "Error: Telegram credentials are missing."
        print(error_msg)
        # We raise an error so Prefect knows the task failed
        raise ValueError(error_msg)

    # 2. Prepare URL and Payload
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": information,
        "parse_mode": "Markdown"
    }

    # 3. Log the attempt
    print(f"🚀 Sending Information with Telegram Chat ID: {TELEGRAM_CHAT_ID}...")

    try:
        # 4. Send POST request
        response = requests.post(url, json=data)
        
        # 5. Check HTTP Status
        if response.status_code == 200:
            print("Message sent successfully.")
        else:
            # If Telegram refuses, we log it and RAISE an exception to trigger Prefect retry
            error_details = f"Telegram API Refused: {response.status_code} - {response.text}"
            print(error_details)
            raise Exception(error_details)
            
    except Exception as e:
        # 6. Handle Network/Connection Errors
        error_str = str(e).lower()
        clean_error_msg = ""

        if "connection" in error_str or "dns" in error_str:
            clean_error_msg = "Network Error: Failed to connect to Telegram API."
        elif "timeout" in error_str:
            clean_error_msg = "Timeout Error: Telegram API did not respond."
        elif "ssl" in error_str:
            clean_error_msg = "SSL Error: Certificate verification failed."
        else:
            clean_error_msg = f"Transmission Failed: {e}"

        print(clean_error_msg)
        
        # CRITICAL: Re-raise the exception so Prefect counts this as a failure and retries
        raise Exception(clean_error_msg)

@flow(name="Daily Image Generator Flow", log_prints=True)
def main_flow():
    """
    The main orchestrator. It fetches a prompt, generates an image, 
    sends it to Telegram, and logs the result to Google Sheets.
    """
    
    # 1. INITIALIZE VARIABLES
    # We set default values to prevent "UnboundLocalError" if the code crashes early.
    prompt_text = "No Prompt"
    last_status = "UNKNOWN"
    status_information = "Process Started"
    
    # Get current server time for the log
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        ws_process, ws_done = get_google_sheets()
    except Exception as e:
        # SAFE LOGGING: Connection errors usually don't leak secrets, 
        # but it's better to be generic just in case.
        print("❌ CRITICAL ERROR: Failed to connect to Google Sheets.")
        print("   (Check credentials.json or API limits)")
        # STOP execution by raising the error
        raise Exception("Google Sheets Connection Failed")

    try:
        # 2. FETCH PROMPT
        # Calls the task to get text from the 'Process' sheet
        prompt_text = get_prompt()

        # If the sheet is empty (returns None), we stop the flow immediately.
        if prompt_text is None or prompt_text.strip() == "":
            print("🛑 No prompt found. Stopping flow.")
            return

        # 3. GENERATE IMAGE
        # Calls the task. Can return: Bytes (Success), String (Warning), or None (Critical Error).
        result = generate_img(prompt_text)

        # --- CHECK RESULT TYPE ---
        if result is None:
            # CASE A: CRITICAL SERVER ERROR (Result is None)
            print("❌ Failed to generate image. Stopping flow.")
            send_information("❌ Sorry, failed to generate image due to server error.")

            last_status = "FAILED"
            status_information = "❌ Sorry, failed to generate image due to server error."   
            
        elif isinstance(result, str):
            # CASE B: SPECIFIC WARNING / QUOTA LIMIT (Result is Text)
            # We send the warning text directly to the user.
            send_information(result)

            last_status = "FAILED"
            status_information = result
            
        else:
            # CASE C: SUCCESS (Result is Image Bytes)
            
            # 4. SEND TO TELEGRAM
            # We use the prompt text as the caption so we know what generated the image.
            to_telegram(caption=prompt_text, img=result)

            # 5. UPDATE STATUS (Success)
            last_status = "SUCCESS"
            status_information = "Image sent to Telegram successfully."

            # 6. CLEAN UP QUEUE (CRITICAL FIX)
            # We delete ROW 2 (the data we just used), not the column.
            # This ensures the next run picks up the next prompt.
            print("🧹 Cleaning up processed row...")
            ws_process.delete_rows(2)

    except Exception as e:
        # 7. ERROR HANDLING (Safe & Graceful Failure)
        last_status = "FAILED"
        
        # Convert error to string for analysis (internal only)
        error_str = str(e).lower()
        
        # --- SAFE ERROR CATEGORIZATION ---
        # We define a "Clean Message" to print and save to Sheets.
        # This prevents the raw URL (with Token) from being saved.

        if "connection" in error_str or "max retries" in error_str:
            clean_msg = "Network/Connection Error (Internet or DNS)"
        elif "401" in error_str or "unauthorized" in error_str:
            clean_msg = "Authentication Error (Check API Keys)"
        elif "429" in error_str or "quota" in error_str:
            clean_msg = "Rate Limit / Quota Exceeded"
        elif "timeout" in error_str:
            clean_msg = "Operation Timed Out"
        elif "json" in error_str or "decode" in error_str:
            clean_msg = "API Response Error (Invalid JSON)"
        else:
            clean_msg = "Internal Error (Details hidden for security)"

        # Print the CLEAN message to console
        print(f"🔥 Flow Failed: {clean_msg}")
        
        # Save the CLEAN message to the status variable (for the Sheet)
        status_information = clean_msg 
        
        # We raise the exception using the CLEAN message.
        # This ensures Prefect marks the flow as Failed, but the log remains safe.
        raise Exception(clean_msg)

    finally:
        # 8. LOGGING (Always Runs)
        # --- SAFE NESTED TRY-EXCEPT (NO RAW ERROR PRINTING) ---
        try:
            print("📝 Logging result to spreadsheet...")
            ws_done.append_row([prompt_text, last_status, status_information, current_time])
        except Exception:
            # We DO NOT print 'final_e' here to avoid any potential leaks.
            # We just print a generic static message.
            print("❌ Final Logging Failed: Google Sheets not accessible or Network Error.")

if __name__ == "__main__":
    # ==========================================
    # 🚀 EXECUTION MODE
    # ==========================================

    # --- OPTION 1: FOR GITHUB ACTIONS (ACTIVE) ---
    # This calls the function immediately (Run Once).
    # GitHub's YAML scheduler handles the timing (CRON).
    # When finished, the script exits to save server resources.
    main_flow()

    # --- OPTION 2: FOR LOCAL SERVER / VPS (COMMENTED OUT) ---
    # Use this if you run the script on your own laptop or a 24/7 server.
    # The '.serve()' method keeps the script running indefinitely 
    # and handles the scheduling internally.
    
    # main_flow.serve(
    #     name="deployment-daily-image-generator",
    #     # cron="0 7 * * *", # Run daily at 07:00 AM (server time)
    #     interval=60,        # Or run every 10 seconds (for testing)
    #     tags=["ai", "daily"]
    # )