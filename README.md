# 🎨 Automated Image Pipeline: Prefect ETL Bot

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)
![Prefect](https://img.shields.io/badge/Prefect-Orchestration-070E28?logo=prefect&logoColor=white)
![HuggingFace](https://img.shields.io/badge/AI-Stable%20Diffusion%2FFlux-FFD21E?logo=huggingface&logoColor=black)
![Google Sheets](https://img.shields.io/badge/Google%20Sheets-ETL%20Source-34A853?logo=googlesheets&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Delivery-26A5E4?logo=telegram&logoColor=white)
![Status](https://img.shields.io/badge/Status-Active-success)

## 📌 Overview
**Automated Image Pipeline** is a robust **ETL (Extract, Transform, Load)** system designed to automate the creation and distribution of AI-generated art.

Orchestrated by **Prefect**, this bot acts as a bridge between your ideas and your audience. It extracts text prompts from a Google Sheet, transforms them into high-quality images using **Hugging Face's Inference API** (Stable Diffusion XL / Flux), and instantly publishes them to a **Telegram Channel**. It features "Do-or-Die" connection logic, automated queue management, and comprehensive activity logging.

## ✨ Key Features

### 🤖 AI-Powered Generation
* **Serverless Inference:** Utilizes `HuggingFace InferenceClient` to access state-of-the-art models (SDXL/Flux) without needing local GPU resources.
* **In-Memory Processing:** Handles image data as Byte Streams (RAM) to avoid disk I/O, ensuring speed and privacy.

### 📊 Google Sheets Integration (ETL)
* **Queue Management (Extract):** Reads the oldest prompt from a "Process" worksheet.
* **Auto-Cleaning:** Automatically removes processed rows to maintain a clean queue.
* **Auditing (Load):** Logs every transaction (Success/Failure, Timestamp, Status) into a "Done" worksheet for historical tracking.

### 🛡️ Robust Orchestration
* **Prefect Flows:** Wraps all logic in tasks with automatic **Retry Policies** (3 retries, 5s delay) to handle transient API network glitches.
* **Defensive Programming:** Implements "Do-or-Die" connection checks at startup and distinct error handling for empty queues vs. API failures.
* **Secure Config:** Uses `python-dotenv` and careful environment variable handling to keep API keys safe.

### 📨 Instant Delivery
* **Telegram Bot API:** Direct integration via HTTP POST requests to send high-res images with captions to specific chat IDs.

## 🛠️ Tech Stack
* **Orchestrator:** Prefect (Workflow Management)
* **Language:** Python 3.11
* **AI Provider:** Hugging Face Inference API (`fal-ai` / `stabilityai`)
* **Data Source:** Google Sheets API (`gspread`)
* **Notification:** Telegram Bot API (`requests`)
* **Image Processing:** Pillow (PIL)

## 🚀 The Automation Pipeline
1.  **Connection Check:** Validates access to Google Sheets. If this fails, the flow terminates immediately (Fail Fast).
2.  **Extract:** Fetches the top-most prompt from the *Process* sheet.
3.  **Validate:** Checks if the prompt is valid (not None or empty whitespace).
4.  **Transform (Generate):** Sends the prompt to Hugging Face -> Receives Image Bytes.
5.  **Load (Publish):** Uploads the image to Telegram with the prompt as the caption.
6.  **Cleanup & Log:** Appends the result to the *Done* sheet and deletes the row from the *Process* sheet .

## ⚙️ Configuration (Environment Variables)
Create a `.env` file in the root directory:

```ini
TELEGRAM_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_target_chat_id
HF_TOKEN=your_huggingface_write_token
```

*Note: You also need a `chatbot_key.json` file for Google Service Account credentials.*

## 📦 Local Installation

1. **Clone the Repository**
```bash
git clone https://github.com/viochris/automated-image-pipeline.git
cd automated-image-pipeline
```

2. **Install Dependencies**
```bash
pip install -r requirements.txt
# Requires: prefect, gspread, huggingface_hub, python-dotenv, requests, pillow
```

3. **Run the Automation**
```bash
python img_bot.py
```

### 🖥️ Expected Output
You should see **Prefect** orchestrating the tasks (Extract -> Transform -> Load) in real-time:

```text
🤖 Bot is starting (Local Mode)...
15:30:01.123 | INFO    | Flow run 'daily-image-generator' - Process Started
15:30:02.456 | INFO    | Task run 'Fetch Prompt' - 🔍 Scanning the prompt queue...
15:30:03.789 | INFO    | Task run 'Fetch Prompt' - ✅ Target Acquired: 'Cyberpunk street food vendor in Jakarta, neon lights, 8k'
15:30:04.112 | INFO    | Task run 'Generate Image' - 🎨 Generating Image for: 'Cyberpunk street food vendor...'
15:30:15.223 | INFO    | Task run 'Generate Image' - ✅ Image generated and converted to bytes successfully.
15:30:15.556 | INFO    | Task run 'Send to Telegram' - 🚀 Sending image to Telegram Chat ID: -100123456789...
15:30:16.889 | INFO    | Task run 'Send to Telegram' - ✅ Success: Message delivered to Telegram!
15:30:16.999 | INFO    | Flow run 'daily-image-generator' - 🧹 Cleaning up processed row...
15:30:17.100 | INFO    | Flow run 'daily-image-generator' - 📝 Logging result to spreadsheet...
15:30:18.000 | INFO    | Flow run 'daily-image-generator' - Finished in state Completed()
```

## 🚀 Deployment Options
This bot supports two release methods depending on your infrastructure:

| Method | Description | Use Case |
| --- | --- | --- |
| **GitHub Actions** | **Serverless.** Uses `cron` scheduling in `.github/workflows/main.yml`. Runs on GitHub servers for free. | Best for daily/scheduled runs without paying for a VPS. |
| **Local / VPS** | **Always On.** Uses `main_flow.serve()` to run as a background service on your own server or Docker container. | Best if you need sub-minute updates or complex triggers. |

---

**Author:** [Silvio Christian, Joe](https://www.linkedin.com/in/silvio-christian-joe)
*"Automate the boring stuff, generate the beautiful stuff."*
