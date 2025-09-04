> 🔥 I indend to turn this into a full-fleged project in the future, please contact me if you want to collaborate.

## ReelsMaker

ReelsMaker is a Python-based/streamlit application designed to create captivating faceless videos for social media platforms like TikTok and YouTube.

### Examples

https://github.com/user-attachments/assets/e65f70a9-8412-4b74-b11b-1009722831bc

https://github.com/user-attachments/assets/aff6b1fb-fd55-4411-bb07-20d65a14ee60

https://github.com/user-attachments/assets/bd1d4948-6a54-45c6-b121-ffd064c7419f

### Features

- AI-Powered Prompt Generation: Automatically generate creative prompts for your video content.
- Subtitles Generation: Auto-generate subtitles using the subtitle_gen.py module.
- Text-to-Speech with TikTok or elevenlabs Voices: Use the tiktokvoice or elevenlabs to add synthetic voices to your videos.

## Installation

```sh
git clone https://github.com/steinathan/reelsmaker.git
cd reelsmaker
```

create a virtual environment with Python 3.11 or 3.12 (pyaudioop is not available in Python 3.13) and install dependencies

To switch to Python 3.12:
1. Check your current Python version: Run `python --version` in your terminal.
2. If you have Python 3.13, download and install Python 3.12 from https://www.python.org/downloads/ (select the latest 3.12.x version).
3. During installation, ensure you check "Add Python to PATH" if prompted.
4. After installation, verify: Run `py --list` to see available versions, then `py -3.12 --version` to confirm 3.12 is available.
5. Create the venv using Python 3.12: `py -3.12 -m venv venv` (or use the full path if needed, e.g., `C:\Users\YourUser\AppData\Local\Programs\Python\Python312\python.exe -m venv venv`).

```sh
$ python -m venv venv
$ venv\Scripts\activate   # On Windows
# or
$ source venv/bin/activate   # On macOS/Linux
$ pip install -r requirements.txt
```

If you encounter ModuleNotFoundError for pydantic_core._pydantic_core, try reinstalling pydantic and pydantic-core:
```sh
$ pip uninstall pydantic pydantic-core
$ pip install pydantic pydantic-core
```

copy and update the `.env`

```sh
$ cp .env.example .env
```
Edit the `.env` file and set values for all required environment variables, such as:
- TOGETHER_API_KEY: Get this from [Together AI](https://together.ai/) by signing up and generating an API key in your dashboard.
- SENTRY_DSN: Obtain this from [Sentry](https://sentry.io/) by creating a project and copying the DSN from your project settings.
- OPENAI_MODEL_NAME: Use the model name you want to use from [OpenAI](https://platform.openai.com/docs/models), e.g., `gpt-3.5-turbo` or `gpt-4`.

These must be valid strings or the application will fail to start.

start the application

```sh
$ streamlit run reelsmaker.py
```

### Contributing

Contributions are welcome! Please open an issue or submit a pull request for any improvements or bug fixes.

### License

This project is licensed under the MIT License - see the LICENSE file for details
