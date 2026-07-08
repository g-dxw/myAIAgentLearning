from langchain.chat_models import init_chat_model
from os import path
from dotenv import load_dotenv
import os

# 读取上级两级的 local.env
script_dir = path.dirname(__file__)
env_file_path = path.abspath(path.join(script_dir, "..", "..", "local.env"))
load_dotenv(dotenv_path=env_file_path)

API_KEY = os.getenv("API_KEY")

if not API_KEY:
    raise ValueError("未读取到 API_KEY")

# 中转站兼容 OpenAI
free_model = init_chat_model(
    model="tokeness/free",
    model_provider="openai",
    api_key=API_KEY,
    base_url="https://tokeness.io/v1",
    temperature = 0
)